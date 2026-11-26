#!/usr/bin/env python3
"""E116 s0 C2: write contracts/mapper/v1/osdu-vocabulary.json (ophiolite.osdu-vocabulary/1) from a checkout of OSDU
data-definitions at tag v0.30.1 (https://community.opengroup.org/osdu/data/data-definitions, Apache-2.0).

    python contracts/tools/osdu-vocabulary.py <dd-checkout>            # rewrite the document
    python contracts/tools/osdu-vocabulary.py <dd-checkout> --check    # exit 1 naming the first difference

It refuses a checkout whose HEAD is not PIN's commit (both named) and a file whose sha256 is not PIN's (the file named)
before it reads anything else. The kinds are each schema file's own x-osdu-schema-source; units, unit quantities and
curve families are every active row of their lists; the coordinate reference systems are the codes of
contracts/vocabulary/v1/coordinate-systems.json that the list holds, and the others with the reason. Standard library
only; nothing is fetched (run it against a checkout made by hand, the command in the lane's Validation Record).

E116 s3 (D1): it also vendors the schemas, unmodified, beside the document (mapper/v1/osdu/<tag>/, the data-definitions
paths kept so every relative $ref resolves unchanged) with LICENSE and a NOTICE: the eight kinds and CLOSURE, the files
their $ref reach, which must be exactly PIN's (a ref that leaves Generated/, names a URL or reaches an unpinned file is
refused, and so is a pinned file no ref reaches). --check names a vendored file whose bytes differ, or one missing or
extra. The vocabulary gains sampling_domains, the active WellLogSamplingDomainType codes.

E116 s3 C2 (D8): run against the repository's own document, --check is also the one command for the two other files
pinned to the same checkout: the Connectors' units.json must equal tools/units-from-osdu.py's output from this
checkout's lists, and contracts/vocabulary/v1/quantities.json must name PIN's commit and only active curve families.

E210 s0b (D-1, D-3, D-6): run on the repository's own document it also writes, and --check regenerates, the `family_from`
rule of each FAMILY_ROWS row of quantities.json (`family_rules`, `family_units`), reading LogCurveType.1.json and
PropertyType.1.json of the same checkout, pinned apart in FAMILY_PIN (PIN and osdu-vocabulary.json do not change) and
recorded in quantities.json's `osdu.family_files`. A row's `family_from.ruled` entries (a supervisor's or owner's ruling,
each with its source) are data, never generated: kept as they are when writing, and not compared by --check.
"""
import collections
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import posixpath
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

CONTRACTS = Path(__file__).resolve().parents[1]
OUT = CONTRACTS / 'mapper/v1/osdu-vocabulary.json'
SYSTEMS = CONTRACTS / 'vocabulary/v1/coordinate-systems.json'
# D8: the files pinned to the same checkout, checked by --check when it reads the repository's own document
COMPANIONS = {'units_tool': CONTRACTS.parents[1] / 'ophiolite-connectors/tools/units-from-osdu.py',
              'units': CONTRACTS.parents[1] / 'ophiolite-connectors/src/asset_connectors/units.json',
              'quantities': CONTRACTS / 'vocabulary/v1/quantities.json'}
# The tag and commit are the folder block's (folder-schema.json's osdu consts), so the folder and the vocabulary name one
# source; kept out of this file, which runs git, where the monorepo inventory would read a commit as a component's.
OSDU = json.loads((CONTRACTS / 'mapper/v1/folder-schema.json').read_text(encoding='utf-8'))['properties']['osdu']['properties']
REFERENCE = 'ReferenceValues/Manifests/reference-data/'
UNITS, QUANTITIES = REFERENCE + 'OPEN/UnitOfMeasure.1.json', REFERENCE + 'OPEN/UnitQuantity.1.json'
FAMILIES, CRS = REFERENCE + 'LOCAL/LogCurveFamily.1.json', REFERENCE + 'LOCAL/CoordinateReferenceSystem.1.json'
SAMPLING = REFERENCE + 'OPEN/WellLogSamplingDomainType.1.json'
NOTICE = '''OSDU data-definitions schemas, vendored unmodified (E116 s3).

Repository: {repository}
Tag: {tag}
Commit: {commit}
Licence: {licence} (LICENSE beside this file)

The files under Generated/ are the data-definitions files of these paths, byte for byte: the eight kinds ophiolite-mapper
writes or names and every schema their $ref reach. Each is listed with its sha256 and size in ../../osdu-vocabulary.json
(source.files), written by contracts/tools/osdu-vocabulary.py, whose --check proves the bytes.
'''
PIN = {
    'repository': 'https://community.opengroup.org/osdu/data/data-definitions',
    'tag': OSDU['tag']['const'], 'commit': OSDU['commit']['const'], 'committed': '2026-10-05', 'licence': 'Apache-2.0',
    'files': {
        'Generated/master-data/Well.1.5.0.json': ('fbf0317863a4a5c9e35a6511a0306ea7406b5d972be10111414baca9c5c701ca', 23378),
        'Generated/master-data/Wellbore.1.5.1.json': ('5c4e34754b07ddcaf3409e1340d7847983938ce9b19bebad06db3dd7a994311f', 29462),
        'Generated/work-product-component/WellLog.1.5.0.json': ('e1a2be27446291f4db94d4fe1077c7bf217a6ee9c6f096be690fb72dbaf269e5', 38041),
        'Generated/work-product-component/WellboreMarkerSet.1.5.1.json': ('1406fe4eb2202b0dda8c2cb4f99d2d04cd349874626edb57145878a7fc3ad741', 19825),
        'Generated/work-product-component/WellboreTrajectory.1.4.0.json': ('38e2136ccdac9119d6320a979a8e53f2e3bdb5bfb24c8ca8396730329d00fbc9', 34890),
        'Generated/work-product-component/SeismicHorizon.2.1.0.json': ('ebf28da8e3e7e76c83f40f6da77915dd12fb871f5f3142aae0be37ae0964984c', 19108),
        'Generated/dataset/File.Generic.1.1.0.json': ('908cdf2888d87b20832b66328b14d74a8c9d7312657de40db7947599cd7ecaae', 5752),
        'Generated/manifest/Manifest.1.0.0.json': ('15e69c5fb2fa25dd057e3bd99a46c63500de3b9cc263c3a38c254bb79d4a3b16', 4033),
        UNITS: ('330ebce827cce16695dcec961c6c508f3f0d5fdb7a4821c20ef2262ee03bbd3c', 3022637),
        QUANTITIES: ('780bcec184b89dc9bb91c921414705c4eb821917c51b2b04538898ce40c1d408', 583475),
        FAMILIES: ('71a00709ca0d72c7cab00e07a2d04f19ff3c66aeea908135d16b1678c8244229', 3152746),
        CRS: ('204e28d6ef99fd478dca42f817baea549c1d8395b3a077f49e7960acf417cebf', 17452573),
        SAMPLING: ('0a29ef3e5d278c386d36d1687d1cfe22ea3ecc1e2b77d36513668a952949dc5a', 6436),
        'LICENSE': ('fba304c4d24d01b1cd07983baf4bd33e0b66c53073c32197645cd53119d6dc85', 11400),
    },
    # E116 s3: the schemas the eight kinds' $ref reach (the lane's logs/closure.txt), vendored with them
    'closure': {
        'Generated/abstract/AbstractAccessControlList.1.0.0.json': ('8c87bf393706b335da0565c6490c7c4337ceadb15f5b9335f4670901ec87cbc3', 1993),
        'Generated/abstract/AbstractAliasNames.1.0.0.json': ('24acb068a2293ea19c5c2909067adb182c047f2ca3db9addd66680c5f0695caf', 2847),
        'Generated/abstract/AbstractAnyCrsFeatureCollection.1.0.0.json': ('4f1b787b3fcce3ea1c3523bb802a927c4e55423978d6d5d6f9fd5eb436c489aa', 22935),
        'Generated/abstract/AbstractAnyCrsFeatureCollection.1.1.0.json': ('59bf1ceb812ea37401ba0f15f216bab572455406547a18cd076ecb6ada370dc9', 23824),
        'Generated/abstract/AbstractColumnBasedTable.1.2.1.json': ('e4b5570b2fae31bb150138a70d3cc4ac6c1fb7d17efa8ae6d8e98a75f8f37235', 6864),
        'Generated/abstract/AbstractCommonResources.1.0.0.json': ('9a4d2f8625ca0ab239759576e5e6ce1cb93b82d83618c4b6338a1dfe0659f4c3', 5110),
        'Generated/abstract/AbstractCommonResources.1.0.1.json': ('d50c1e1c3d685862d52096916f25f175fe398ccab025476c891cb6502b0504d9', 5293),
        'Generated/abstract/AbstractContact.1.0.0.json': ('da54601ad5772c96ed7d1642c6590882a78f2dcdcebac97a2aa32fe226b6a167', 4348),
        'Generated/abstract/AbstractContact.1.1.0.json': ('ac39fcee6ebcf4bf4b565c7c5ea1ffa2e954974f108862e088409b54d99dd58c', 5388),
        'Generated/abstract/AbstractDataset.1.0.1.json': ('f316c24287971652569646ae3d21490fc8c3d3dd17af41d7e4b2fba9ee9c53b6', 3374),
        'Generated/abstract/AbstractFacet.1.0.0.json': ('dca46f4a5ea58ea9fcf11358b678462115a06b002931e3a0e55936b0945ffc4b', 3015),
        'Generated/abstract/AbstractFacility.1.1.0.json': ('5a0f1b87f01c615eed3aa8a316be0128778b034322db014f54f4c539a3d8689d', 5998),
        'Generated/abstract/AbstractFacilityEvent.1.1.0.json': ('83d1dc682dfa4fec2ae2affbae1cc5e497b5d83eb9520789cc38b3f54cc5804f', 2311),
        'Generated/abstract/AbstractFacilityOperator.1.1.0.json': ('beeeb7a35777ed1cd7f4e60475423f0c9145c56a9b56e98a16ed7ef4c9d3a8a0', 2400),
        'Generated/abstract/AbstractFacilitySpecification.1.0.0.json': ('632ae8b5c43d014c03e8b195eb9855bfcc90dab9c405c7a1d859e14aea9e45f4', 3007),
        'Generated/abstract/AbstractFacilityState.1.1.0.json': ('bdb5da6310e30465599baecbd4530a9881ffc237839863545cc100f5ff5327b4', 2117),
        'Generated/abstract/AbstractFacilityVerticalMeasurement.1.0.0.json': ('59fe7d7c0e204f9e3a36d9a8e88dd6065c9c461672bc84ebda3acaf7f09d6386', 6629),
        'Generated/abstract/AbstractFeatureCollection.1.0.0.json': ('11b117bf1856d71914ca26e681bd508c527301d37d07ce189bf7f9ec256554b9', 17997),
        'Generated/abstract/AbstractFile.1.0.1.json': ('0505bae76d6f84785f1e75c67c58cdad626f2b261682bcfb37f35a50f187a07c', 1684),
        'Generated/abstract/AbstractFileSourceInfo.1.0.1.json': ('0496cee4cc103ddc1a2c99d60a6447f8b2b87cad0605203f7b3d1f529d1af1ba', 4688),
        'Generated/abstract/AbstractGeoBasinContext.1.0.0.json': ('ca46efabecf6efe86f5b868deff720b26ca7d1a2e125def8b1f6ff572cfabc25', 1923),
        'Generated/abstract/AbstractGeoContext.1.0.0.json': ('193d2e7ea1f009d5699eea67acb8a06325a2bb7a5d24967e40d7accaa82860f1', 1346),
        'Generated/abstract/AbstractGeoFieldContext.1.0.0.json': ('12bfeaffceddd6cd025b2427911f152c17f2767ecd11e3288cc39716c74ef318', 1529),
        'Generated/abstract/AbstractGeoPlayContext.1.0.0.json': ('f150c876f2f67bb6c5fccfffb2745af160525039b1bb035526ec0ec2457bf505', 1912),
        'Generated/abstract/AbstractGeoPoliticalContext.1.0.0.json': ('573c7a3e1fdfda36a606b169d123202e482e8d57ef4753bb6a5b30f37df57d8d', 2086),
        'Generated/abstract/AbstractGeoProspectContext.1.0.0.json': ('45a1b9be840ec3e3872de7a5c3d8f038de0a7f5e12cdad6a1028186c82cec7d2', 1972),
        'Generated/abstract/AbstractLegalParentList.1.0.0.json': ('e4907fa3131443b04eb656990dfca2d74442d1a1aba535f2dd4d78f43d6139da', 2132),
        'Generated/abstract/AbstractLegalTags.1.0.0.json': ('f74b0bce76f90f1f59fb85cd9f9aaa24ce9eee3527fcb90459bfee4f20e80fc8', 2180),
        'Generated/abstract/AbstractLocationUncertainty.1.0.0.json': ('46168f8b84aadf18453a797a4177344bbff7d4e5171d389052f7df8ea2ed083e', 2944),
        'Generated/abstract/AbstractMaster.1.2.0.json': ('87a98a58e4777600849b98fbf0ba504d76c1e39b0d1c86048cf01f14878b68c6', 4178),
        'Generated/abstract/AbstractMetaItem.1.0.0.json': ('336db02cef1715e1c89ba3c9621effb15659019ed1baf119f8aaf36b47a65d3e', 8666),
        'Generated/abstract/AbstractPropertyType.1.0.0.json': ('8dfae9c25dd20e68b37195078de2c7fc0b6e0c4b167517da492cd84f1037822c', 2187),
        'Generated/abstract/AbstractReferencePropertyType.1.2.1.json': ('84ea633981b07330da47e85a18fcbddbff7a0b8f00d0cd64501424bd0603be02', 5841),
        'Generated/abstract/AbstractRemark.1.0.0.json': ('6af1c3c175aabe11007352697c89e118175efd3dff88ae15415c6adba54847a1', 1914),
        'Generated/abstract/AbstractRepresentation.1.0.0.json': ('8ed930261834a0fee573ddc0f0f6a8ee8f45b3a8c7965dd24ace47e1f3b41621', 6782),
        'Generated/abstract/AbstractSpatialLocation.1.0.0.json': ('d871a68ab821a5df1e010cf2e458239c79b80e6ae1a629a213626f7beba4b889', 6378),
        'Generated/abstract/AbstractSpatialLocation.1.1.0.json': ('ef2f08602f995eee0bce8ed1a205fe58b4436c8c05387172213fcb3dd37bf63b', 6440),
        'Generated/abstract/AbstractTechnicalAssurance.1.0.0.json': ('24605ab997c52ce655b061f99398744ac734ed0c7775e47b32c872e387eb88e5', 9315),
        'Generated/abstract/AbstractTechnicalAssurance.1.2.0.json': ('8898aa5942099af5008eeed491f3a4e03ca28c685446ca34f7a2b925c6198650', 18272),
        'Generated/abstract/AbstractTimeSeriesLink.1.0.0.json': ('ed8104e8a4ef5ef49729af1f7be81408e17388f200a75986c79857dd5e64615a', 1956),
        'Generated/abstract/AbstractWPCGroupType.1.2.0.json': ('279cbd398ecaef15224ec3cf92f5e8f3d820f94d6c9b2bdf2f82a2817017cb2c', 6129),
        'Generated/abstract/AbstractWellboreDrillingReason.1.1.1.json': ('856e570ed81252fdddfe3e09c026cade6b8255466220bfcfb118061793066cb0', 2773),
        'Generated/abstract/AbstractWorkProductComponent.1.1.0.json': ('dbb4f9f55eeac42f20b228073b3d2362ad882a53ef8f4555cf0bd70f6eaf93d1', 5626),
        'Generated/manifest/GenericDataset.1.0.0.json': ('407812b1682ce5a67570b35b32175a3bc67c46438a5f015b3abc9938d2282368', 8202),
        'Generated/manifest/GenericMasterData.1.0.0.json': ('e80a4ec97d890c8ddd937fc5fdfd7e8d83a49a01da01006968e904715eeac102', 8119),
        'Generated/manifest/GenericReferenceData.1.0.0.json': ('245bd19ac4bd2595b215720c84052a8d7383e9e8efb319d050dc625a9d3521ad', 8639),
        'Generated/manifest/GenericWorkProduct.1.0.0.json': ('2eda8465ec0f6862c12ff71dbde719f079b0fda9adfc30970acca376860cc69b', 15650),
        'Generated/manifest/GenericWorkProductComponent.1.0.0.json': ('c89d3cbe161b6366d24efc9d1103d47b3e1ac405ff4d9a6196d381bd9450ef37', 15755),
    },
}
ORDER = ('kinds', 'units', 'quantities', 'curve_families', 'sampling_domains', 'crs', 'crs_absent', 'source')
# E210 s0b (D-6): the two further files the family rule reads, at PIN's commit; kept out of PIN so osdu-vocabulary.json's
# source block (every PIN file) and its test's map stay as they are.
CURVE_TYPES, PROPERTY_TYPES = REFERENCE + 'LOCAL/LogCurveType.1.json', REFERENCE + 'OPEN/PropertyType.1.json'
FAMILY_PIN = {
    CURVE_TYPES: ('1aff161655609de5e409b4db6ce057b8892a684e574cb2441441da902e2ee283', 76541097),
    PROPERTY_TYPES: ('34aa87664d0f4d8b9a64d64d8a18b48a68042cfffeb77c4f2d456b827c1b7d87', 6406435),
}
# E210 s0b (§2): the curve families that carry a rule in quantities.json, one row each (a row is found by its
# osdu_log_curve_family; a missing one is added with the family's name, in this order).
FAMILY_ROWS = ('Gamma Ray', 'Bulk Density', 'Thermal Neutron Porosity', 'Neutron Porosity', 'Compressional Slowness',
               'Shear Slowness', 'Resistivity', 'Spontaneous Potential', 'Caliper', 'Borehole Diameter',
               'Photoelectric Factor')
FAMILY_SOURCE = ("Ophiolite's rule over PWLS-3 and the PWLS property tree, not an assignment OSDU publishes: OSDU "
                 "data-definitions at the osdu block's commit, LogCurveType.1.json (every company's row of a mnemonic), "
                 "PropertyType.1.json and LogCurveFamily.1.json. A mnemonic names this family when the property types of "
                 "all its rows lie on one line of the property tree and the nearest one at or above the deepest that "
                 "carries a family of its own name carries this one. The units are the Energistics symbols (units.json) "
                 "of the family's unit quantity, or E52's suggesting units where the row has them, less a symbol LAS "
                 "files write for another unit (MV, a millivolt in LAS, is a megavolt in units.json).")
# E210 s0b C2b (coordinator default, supervisor approved 25 Nov): symbols a family's rule leaves out although they are of the
# family's unit quantity. LAS files write MV for millivolts; units.json (E64) reads MV as megavolt, so a curve suggested
# Spontaneous Potential in MV would be scaled by 1e9 by change_units on a request to mV. Left out, SP in MV suggests nothing.
# The grep that found no other such symbol is in the lane's logs/c2b-collisions.txt.
FAMILY_UNITS_LEFT_OUT = {'Spontaneous Potential': ('MV',)}


class Refused(Exception):
    pass


def _suffix(reference_id, kind):
    return unquote(reference_id.rsplit(f'--{kind}:', 1)[1].rstrip(':'))


def read(checkout, pin):
    """The pinned files' bytes, after the commit and every digest are confirmed."""
    head = subprocess.run(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    if head != pin['commit']:
        raise Refused(f'the checkout is at {head or "no commit"}, not {pin["tag"]} {pin["commit"]}')
    raw = {}
    for path, (digest, _) in sorted(pinned(pin).items()):
        file = Path(checkout) / path
        if not file.is_file(): raise Refused(f'{path} is missing from the checkout')
        raw[path] = file.read_bytes()
        if hashlib.sha256(raw[path]).hexdigest() != digest: raise Refused(f'{path} does not have the pinned sha256')
    closure(raw, pin)
    return raw


def pinned(pin):
    return {**pin['files'], **pin.get('closure', {})}


def _refs(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == '$ref' and isinstance(value, str): yield value
            else: yield from _refs(value)
    elif isinstance(node, list):
        for value in node: yield from _refs(value)


def closure(raw, pin):
    """Every $ref of the kinds, followed: each must name a pinned file under Generated/, and every pinned schema must be
    reached (so PIN's closure is exactly what the kinds need)."""
    reached, todo = set(), [p for p in pin['files'] if p.startswith('Generated/')]
    while todo:
        path = todo.pop()
        if path in reached: continue
        reached.add(path)
        for ref in _refs(json.loads(raw[path])):
            target = ref.split('#', 1)[0]
            if not target: continue
            if '://' in target: raise Refused(f'{path} refers to {ref}, outside the checkout')
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
            if not resolved.startswith('Generated/'): raise Refused(f'{path} refers to {ref}, outside Generated/')
            if resolved not in raw: raise Refused(f'{path} refers to {resolved}, which is not pinned')
            todo.append(resolved)
    unreached = sorted(p for p in pinned(pin) if p.startswith('Generated/') and p not in reached)
    if unreached: raise Refused(f'{unreached[0]} is pinned but no kind refers to it')


def vendored(raw, pin):
    """The vendored directory's files: the schemas byte for byte, LICENSE and the NOTICE."""
    files = {p: raw[p] for p in sorted(pinned(pin)) if p.startswith('Generated/')}
    files['LICENSE'] = raw['LICENSE']
    files['NOTICE'] = NOTICE.format(**pin).encode()
    return files


def document(raw, pin, systems):
    rows = {path: json.loads(raw[path])['ReferenceData'] for path in (UNITS, QUANTITIES, FAMILIES, CRS, SAMPLING)}
    active = {path: [r['data'] for r in items if not r['data'].get('InactiveIndicator')] for path, items in rows.items()}
    kinds = sorted(json.loads(raw[path])['x-osdu-schema-source'] for path in pin['files'] if path.startswith('Generated/'))
    domains = sorted(d['Code'] for d in active[SAMPLING])
    units = sorted(({'id': d['Code'], 'dimension': _suffix(d['UnitQuantityID'], 'UnitQuantity')} for d in active[UNITS]), key=lambda r: r['id'])
    quantities = sorted(({'code': d['Code'], 'dimension': d['UnitDimension'], 'members': list(d.get('MemberUnits', []))}
                         for d in active[QUANTITIES]), key=lambda r: r['code'])
    families = sorted(({'name': d['Name'], 'quantity': _suffix(d['UnitQuantityID'], 'UnitQuantity')} for d in active[FAMILIES]),
                      key=lambda r: r['name'])
    held = {(d.get('CodeSpace'), d.get('Code')): d['ID'] for d in active[CRS]}
    crs, absent = [], []
    for code in systems:
        space, number = code.split(':', 1)
        if (space, number) in held: crs.append({'code': code, 'id': held[(space, number)]})
        else: absent.append({'code': code, 'reason': f'not in {CRS.rsplit("/", 1)[1]} at {pin["tag"]}'})
    source = {'repository': pin['repository'], 'tag': pin['tag'], 'commit': pin['commit'], 'committed': pin['committed'],
              'licence': pin['licence'], 'files': [{'path': p, 'sha256': d, 'bytes': b} for p, (d, b) in sorted(pinned(pin).items())]}
    return {'schema': 'ophiolite.osdu-vocabulary/1', 'source': source, 'kinds': kinds, 'units': units, 'quantities': quantities,
            'curve_families': families, 'sampling_domains': domains, 'crs': crs, 'crs_absent': absent}


def text(doc):
    """One row per line, so a review sees each changed row."""
    out = ['{', f' "schema": {json.dumps(doc["schema"])},', f' "source": {json.dumps(doc["source"], ensure_ascii=False)},']
    keys = [k for k in ORDER if k != 'source']
    for i, key in enumerate(keys):
        rows = ',\n'.join('  ' + json.dumps(v, ensure_ascii=False, sort_keys=True) for v in doc[key])
        body = f'[\n{rows}\n ]' if doc[key] else '[]'
        out.append(f' "{key}": {body}' + (',' if i < len(keys) - 1 else ''))
    return '\n'.join(out) + '\n}\n'


def difference(old, new):
    """The first difference, named by list."""
    for key in ORDER:
        a, b = old.get(key), new.get(key)
        if a == b: continue
        if key == 'kinds':
            gone, added = sorted(set(a or ()) - set(b)), sorted(set(b) - set(a or ()))
            return f'kinds: {", ".join(gone)} absent' if gone else f'kinds: {", ".join(added)} new'
        if key == 'source': return f'source: the pin differs ({(a or {}).get("commit")} in the document, {b["commit"]} here)'
        if isinstance(a, list) and isinstance(b, list):
            changed = sum(x != y for x, y in zip(a, b)) + abs(len(a) - len(b))
            return f'{key}: {changed} rows differ'
        return f'{key} differs'
    return None


def companion_difference(checkout, doc, pin, companions):
    """The first way units.json or quantities.json disagrees with this checkout, named."""
    spec = importlib.util.spec_from_file_location('units_from_osdu', companions['units_tool'])
    units = importlib.util.module_from_spec(spec); spec.loader.exec_module(units)
    if units.REVISION != pin['commit']: return f'units-from-osdu.py REVISION is {units.REVISION}, not {pin["commit"]}'
    units.OUT = Path(companions['units'])
    with contextlib.redirect_stdout(io.StringIO()):
        same = units.main(['units-from-osdu.py', str(checkout / UNITS), str(checkout / QUANTITIES), '--check']) == 0
    if not same: return f'{units.OUT.name} differs from units-from-osdu.py at {pin["commit"]}'
    quantities = json.loads(Path(companions['quantities']).read_text(encoding='utf-8'))
    if quantities['osdu']['commit'] != pin['commit']:
        return f'quantities.json osdu.commit is {quantities["osdu"]["commit"]}, not {pin["commit"]}'
    families = {f['name'] for f in doc['curve_families']}
    for row in quantities['quantities']:
        if row['osdu_log_curve_family'] not in families:
            return f'quantities.json {row["name"]}: {row["osdu_log_curve_family"]} is not an active curve family at {pin["tag"]}'
    family_pin = companions.get('family_pin', FAMILY_PIN)
    return family_difference(quantities, Path(companions['quantities']).read_text(encoding='utf-8'),
                             read_families(checkout, family_pin), family_pin, companions.get('families', FAMILY_ROWS))


# ---- E210 s0b: the family rule ------------------------------------------------------------------------------------

def read_families(checkout, family_pin):
    """FAMILY_PIN's bytes after each digest is confirmed, with the three PIN lists the rule also reads (whose digests and
    commit read() has confirmed)."""
    raw = {}
    for path, (digest, _) in sorted(family_pin.items()):
        file = Path(checkout) / path
        if not file.is_file(): raise Refused(f'{path} is missing from the checkout')
        raw[path] = file.read_bytes()
        if hashlib.sha256(raw[path]).hexdigest() != digest: raise Refused(f'{path} does not have the pinned sha256')
    for path in (UNITS, QUANTITIES, FAMILIES): raw[path] = (Path(checkout) / path).read_bytes()
    return raw


def _id(reference):
    """The record id of an OSDU reference ('{{NAMESPACE}}:reference-data--PropertyType:<id>:'), else None."""
    return reference.split(':')[-2] if isinstance(reference, str) and reference.count(':') >= 2 else None


def _active(raw, path):
    return [r['data'] for r in json.loads(raw[path])['ReferenceData'] if not r['data'].get('InactiveIndicator')]


def family_rules(raw, families):
    """§2 (D-1): {family: sorted mnemonics} for the named families. A mnemonic (the part of a LogCurveType Code after its
    company, upper-cased) names family F when the property types of all its rows lie on one line of the property tree
    (each is the deepest one or an ancestor of it; otherwise the vendors conflict), and walking up from the deepest the
    first property type carrying a family of its own name (case-insensitive) carries F. A mnemonic with no property type,
    a conflict, or no own-name family up to the root names none."""
    types = {d['ID']: d for d in _active(raw, PROPERTY_TYPES)}
    named = collections.defaultdict(list)
    for d in _active(raw, FAMILIES):
        named[_id((d.get('PropertyType') or {}).get('PropertyTypeID'))].append(d['Name'])

    def chain(pid):
        out = []
        while pid and pid not in out:
            out.append(pid); pid = _id((types.get(pid) or {}).get('ParentPropertyTypeID'))
        return out

    def family(pid):
        for p in chain(pid):
            own = [f for f in named.get(p, []) if f.lower() == (types.get(p) or {}).get('Name', '').lower()]
            if own: return own[0]
        return None

    rows = collections.defaultdict(set)
    for d in _active(raw, CURVE_TYPES):
        pid = _id((d.get('PropertyType') or {}).get('PropertyTypeID'))
        if pid: rows[d['Code'].split(':', 1)[1].upper()].add(pid)
    found = {f: [] for f in families}
    for mnemonic in sorted(rows):
        lines = {p: chain(p) for p in rows[mnemonic]}
        deepest = max(sorted(lines), key=lambda p: len(lines[p]))
        if not all(p in lines[deepest] for p in lines): continue
        f = family(deepest)
        if f in found: found[f].append(mnemonic)
    return found


def family_units(raw, families):
    """D-3: {family: sorted unit symbols}: every active unit of the dimension class of the family's unit quantity (the
    symbols units.json holds for that quantity), less FAMILY_UNITS_LEFT_OUT."""
    dimension = {d['Code']: d['UnitDimension'] for d in _active(raw, QUANTITIES)}
    quantity = collections.defaultdict(set)
    for d in _active(raw, FAMILIES):
        if d['Name'] in families: quantity[d['Name']].add(_suffix(d['UnitQuantityID'], 'UnitQuantity'))
    by_class = collections.defaultdict(list)
    for d in _active(raw, UNITS): by_class[_suffix(d['UnitQuantityID'], 'UnitQuantity')].append(d['Code'])
    out = {}
    for name in families:
        if len(quantity[name]) != 1: raise Refused(f'curve family {name} has {len(quantity[name])} unit quantities, not one')
        left_out = FAMILY_UNITS_LEFT_OUT.get(name, ())
        out[name] = sorted(u for u in by_class[dimension[next(iter(quantity[name]))]] if u not in left_out)
    return out


def with_families(quantities, raw, family_pin, families):
    """quantities.json with each family row's generated `family_from` (its `ruled` entries kept) and `osdu.family_files`;
    a missing row is added. Refused when a generated mnemonic is another row's (stop rule 4)."""
    doc = copy.deepcopy(quantities)
    rules, units = family_rules(raw, families), family_units(raw, families)
    rows = {q['osdu_log_curve_family']: q for q in doc['quantities']}
    for name in families:
        if name not in rows:
            rows[name] = {'name': name, 'osdu_log_curve_family': name, 'units': []}
            doc['quantities'].append(rows[name])
        row = rows[name]
        suggesting = (row.get('suggest_from') or {}).get('units')
        generated = list(suggesting) if suggesting else units[name]
        ruled = (row.get('family_from') or {}).get('ruled')
        row['family_from'] = {'mnemonics': rules[name], 'units': generated, 'source': FAMILY_SOURCE,
                              **({'ruled': ruled} if ruled is not None else {})}
        row['units'] = row['units'] + [u for u in generated if u not in row['units']]
    for name in families:
        for other in doc['quantities']:
            if other is rows[name]: continue
            held = set((other.get('suggest_from') or {}).get('mnemonics', [])) | set((other.get('family_from') or {}).get('mnemonics', []))
            for entry in (other.get('family_from') or {}).get('ruled') or []: held |= set(entry.get('mnemonics', []))
            both = sorted(held & set(rules[name]))
            if both: raise Refused(f'{both[0]} would suggest both {name} and {other["name"]}')
    doc['osdu']['family_files'] = [{'path': p, 'sha256': d, 'bytes': b} for p, (d, b) in sorted(family_pin.items())]
    return doc


def quantities_text(doc):
    return json.dumps(doc, indent=1, ensure_ascii=False) + '\n'


def family_difference(committed, text_now, raw, family_pin, families):
    """The first way quantities.json's generated family rules differ from this checkout's, named; `ruled` is not read."""
    generated = with_families(committed, raw, family_pin, families)
    if committed['osdu'].get('family_files') != generated['osdu']['family_files']:
        return 'quantities.json osdu.family_files differs from FAMILY_PIN'
    rows = {q['osdu_log_curve_family']: q for q in committed['quantities']}
    for row in generated['quantities']:
        name = row['osdu_log_curve_family']
        if name not in families: continue
        if name not in rows: return f'quantities.json has no row for the curve family {name}'
        have, want = rows[name].get('family_from') or {}, row['family_from']
        for key in ('mnemonics', 'units'):
            absent, extra = sorted(set(want[key]) - set(have.get(key, []))), sorted(set(have.get(key, [])) - set(want[key]))
            if absent: return f'quantities.json {name}: family_from {key} lacks {absent[0]} ({len(absent)} absent)'
            if extra: return f'quantities.json {name}: family_from {key} has {extra[0]}, which the rule does not give ({len(extra)} extra)'
        if have != want: return f'quantities.json {name}: family_from differs from the generator'
        if rows[name]['units'] != row['units']: return f'quantities.json {name}: units lack a family_from unit'
    return 'quantities.json layout differs' if text_now != quantities_text(generated) else None


def write_families(checkout, companions):
    path, family_pin = Path(companions['quantities']), companions.get('family_pin', FAMILY_PIN)
    doc = with_families(json.loads(path.read_text(encoding='utf-8')), read_families(checkout, family_pin), family_pin,
                        companions.get('families', FAMILY_ROWS))
    path.write_text(quantities_text(doc), encoding='utf-8')


def main(argv, pin=PIN, out=OUT, systems=None, companions=None):
    if companions is None and Path(out) == OUT: companions = COMPANIONS
    args = [a for a in argv if not a.startswith('--')]
    if len(args) != 1:
        print(__doc__.strip().splitlines()[3].strip(), file=sys.stderr); return 2
    if systems is None: systems = [s['code'] for s in json.loads(SYSTEMS.read_text())['systems']]
    try: raw = read(Path(args[0]), pin)
    except Refused as error:
        print(f'osdu-vocabulary: refused: {error}', file=sys.stderr); return 1
    doc = document(raw, pin, systems)
    folder = Path(out).parent / 'osdu' / pin['tag']
    files = vendored(raw, pin)
    if '--check' in argv:
        committed = json.loads(Path(out).read_text(encoding='utf-8')) if Path(out).exists() else {}
        found = difference(committed, doc) or (None if Path(out).read_text(encoding='utf-8') == text(doc) else 'layout differs')
        found = found or vendor_difference(folder, files)
        try: found = found or (companion_difference(Path(args[0]), doc, pin, companions) if companions else None)
        except Refused as error:
            print(f'osdu-vocabulary: refused: {error}', file=sys.stderr); return 1
        print(f'osdu-vocabulary: {found}' if found else 'osdu-vocabulary.json and the vendored schemas equal the generator',
              file=sys.stderr if found else sys.stdout)
        return 1 if found else 0
    if companions:  # E210 s0b: the family rules first, so a refusal writes nothing
        try: write_families(Path(args[0]), companions)
        except Refused as error:
            print(f'osdu-vocabulary: refused: {error}', file=sys.stderr); return 1
    for name, body in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True); (folder / name).write_bytes(body)
    for extra in sorted(set(_present(folder)) - set(files)): (folder / extra).unlink()
    Path(out).write_text(text(doc), encoding='utf-8'); print(f'wrote {out} and {len(files)} files under {folder}'); return 0


def _present(folder):
    return [p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()] if folder.is_dir() else []


def vendor_difference(folder, files):
    """The first vendored file that is missing, extra or not byte-equal, named."""
    present = set(_present(folder))
    for name in sorted(files):
        if name not in present: return f'vendored {name} is missing'
        if (folder / name).read_bytes() != files[name]: return f'vendored {name} differs from the checkout'
    extra = sorted(present - set(files))
    return f'vendored {extra[0]} is not a pinned file' if extra else None


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
