"""Generate tolerant, strict declared-field models from the audited schema snapshot."""
import argparse
import json
import keyword
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT/'ophiolite/contracts'
KEYWORDS = {'$defs','$id','$ref','$schema','additionalProperties','anyOf','const',
            'default','description','discriminator','enum','exclusiveMinimum','items',
            'maxItems','maxLength','maximum','minItems','minLength','minimum','oneOf',
            'pattern','properties','required','title','type','x-ophiolite'}
RENAMES = {'Asset':'ScientificAsset','Curve':'ApplicationCurve','ScientificContext':'ScientificContext'}

def name(value):
    result = re.sub('[^A-Za-z0-9_]', '', value)
    if not result or not result[0].isalpha(): raise ValueError('Invalid model name: '+value)
    return RENAMES.get(result, result)


def python_field(field):
    python_name = re.sub('[^A-Za-z0-9_]', '_', field)
    return python_name + '_' if keyword.iskeyword(python_name) or python_name in ('schema','model_config') else python_name

class Generator:
    def __init__(self):
        self.classes = {}; self.documents = {}; self.origins = {}

    def scan(self, schema, path):
        if not isinstance(schema, dict): raise ValueError(path+': schema must be an object')
        unknown = schema.keys()-KEYWORDS
        if unknown: raise ValueError(path+': unsupported keyword '+sorted(unknown)[0])
        if isinstance(schema.get('additionalProperties'), dict):
            raise ValueError(path+': schema-valued additionalProperties unsupported')
        for key in ('$defs','properties'):
            for field, child in schema.get(key, {}).items(): self.scan(child,path+'/'+key+'/'+field)
        if 'items' in schema: self.scan(schema['items'],path+'/items')
        for key in ('anyOf','oneOf'):
            for i, child in enumerate(schema.get(key, [])): self.scan(child,path+f'/{key}/{i}')

    def model(self, model_name, schema, document):
        model_name = name(model_name)
        schema = {k:v for k,v in schema.items() if k not in ('$schema','$id','$defs','x-ophiolite')}
        old = self.classes.get(model_name)
        if old is not None:
            if old != schema: raise ValueError('Conflicting model '+model_name)
            return model_name
        self.classes[model_name] = schema
        self.origins[model_name] = document
        return model_name

    def expression(self, schema, hint, document):
        if '$ref' in schema:
            reference = schema['$ref']
            prefix = '#/$defs/'
            if not reference.startswith(prefix): raise ValueError('Unsupported model reference: '+reference)
            key = reference[len(prefix):].replace('~1','/').replace('~0','~')
            return self.model(key,self.documents[document]['$defs'][key],document)
        if 'const' in schema: expression = 'Literal['+repr(schema['const'])+']'
        elif 'enum' in schema: expression = 'Literal['+', '.join(repr(x) for x in schema['enum'])+']'
        elif 'anyOf' in schema or 'oneOf' in schema:
            key = 'anyOf' if 'anyOf' in schema else 'oneOf'
            expression = ' | '.join(self.expression(x,hint+str(i),document) for i,x in enumerate(schema[key]))
        else:
            kind = schema.get('type')
            if isinstance(kind,list):
                expression = ' | '.join(self.expression({**schema,'type':t},hint,document) for t in kind)
                return expression
            if kind == 'object' and not schema.get('properties') and schema.get('additionalProperties') is True: expression = 'dict[str, Any]'  # a free-form JSON object
            elif kind == 'object': expression = self.model(hint,schema,document)
            elif kind == 'array': expression = 'list['+self.expression(schema['items'],hint+'Item',document)+']'
            elif kind in ('string','number','integer','boolean','null'):
                expression = {'string':'str','number':'float','integer':'int','boolean':'bool','null':'None'}[kind]
            else: raise ValueError(hint+': missing/unsupported type '+repr(kind))
        fields = []
        for key, target in [('pattern','pattern'),('minLength','min_length'),('maxLength','max_length'),
                            ('minItems','min_length'),('maxItems','max_length'),('minimum','ge'),
                            ('maximum','le'),('exclusiveMinimum','gt')]:
            if key in schema: fields.append(target+'='+repr(schema[key]))
        if 'discriminator' in schema:
            fields.append('discriminator='+repr(python_field(schema['discriminator']['propertyName'])))  # the Python name ('schema' is aliased)
        return 'Annotated['+expression+', Field('+', '.join(fields)+')]' if fields else expression

    def generate(self, documents):
        self.documents = documents
        for path, schema in documents.items():
            self.scan(schema,path)
            self.model(schema['title'],schema,path)
            for key, definition in schema.get('$defs',{}).items(): self.model(key,definition,path)
        emitted = {}; pending = list(self.classes)
        while pending:
            model_name = pending.pop(0); schema = self.classes[model_name]; document = self.origins[model_name]
            if schema.get('type') != 'object': raise ValueError('Non-object named model: '+model_name)
            lines = [f'class {model_name}(Contract):']
            properties = schema.get('properties',{})
            if not properties: lines.append('    pass')
            used = set()
            for field, value in properties.items():
                python_name = python_field(field)
                if python_name in used: raise ValueError('Colliding Python field alias: '+field)
                used.add(python_name)
                if not python_name.isidentifier(): raise ValueError('Unsupported field name: '+field)
                expression = self.expression(value,model_name+name(field.title()),document)
                default = '...' if field in schema.get('required',[]) else repr(value.get('default'))
                extras = ', alias='+repr(field) if python_name != field else ''
                lines.append(f'    {python_name}: {expression} = Field({default}{extras})')
            emitted[model_name] = '\n'.join(lines)
            pending.extend(key for key in self.classes if key not in emitted and key not in pending)
        header = '''# Generated by tools/generate_models.py; do not hand edit.
from __future__ import annotations
from typing import Annotated, Any, ClassVar, Literal
from pydantic import BaseModel, ConfigDict, Field

class Contract(BaseModel):
    model_config = ConfigDict(extra='allow', strict=True, allow_inf_nan=False)
    __strict_extras__: ClassVar[bool] = False
'''
        body = '\n\n'.join(emitted.values())
        rebuild = '\n'.join(f'{model_name}.model_rebuild()' for model_name in emitted)
        return header+'\n\n'+body+'\n\n'+rebuild+'\n'

def documents():
    index = json.loads((CONTRACTS/'registry.json').read_text())
    paths = {'registry-schema.json','profile-schema.json'}
    paths.update(row['path'] for row in index['schemas'])
    return {path:json.loads((CONTRACTS/path).read_text()) for path in sorted(paths)}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    output=Generator().generate(documents()); target=ROOT/'ophiolite/models/generated.py'
    if args.check:
        if target.read_text()!=output: raise ValueError('Generated models differ')
    else: target.write_text(output)
    print(f'Generated models: {len(documents())} schema documents')

if __name__=='__main__': main()
