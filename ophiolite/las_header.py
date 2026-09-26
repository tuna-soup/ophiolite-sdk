"""Read LAS header declarations only; samples are never reconstructed here."""
from dataclasses import dataclass
import math
import re
from .errors import Refused

@dataclass(frozen=True)
class CurveHeader:
    mnemonic: str
    unit: str
    description: str


def _sections(raw):
    if not isinstance(raw,bytes):raise Refused('Supply the original LAS bytes.')
    try:text=raw.decode('utf-8-sig')
    except UnicodeError:raise Refused('This SDK header reader requires UTF-8 LAS input.') from None
    section=None
    for line in text.splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        if line.startswith('~'):
            section=line[1:2].upper()
            if section=='A':return
        elif section is not None:yield section,line


def curves(raw):
    result=[]
    for section,line in _sections(raw):
        if section!='C':continue
        declaration,_,description=line.partition(':')
        match=re.fullmatch(r'([^\s.]+)\s*\.\s*([^\s]*)(?:\s+.*)?',declaration.strip())
        if not match:raise Refused('Cannot read a LAS curve declaration.')
        result.append(CurveHeader(match[1],match[2],description.strip()))
    if not result:raise Refused('LAS input needs a curve header section.')
    return result


def null_marker(raw):
    matches=[]
    for section,line in _sections(raw):
        if section=='W' and re.match(r'NULL\s*\.',line,re.I):
            declaration=line.partition(':')[0].split('.',1)[1].strip()
            try:value=float(declaration)
            except ValueError:raise Refused('LAS missing-value marker must be a finite number.') from None
            if not math.isfinite(value):raise Refused('LAS missing-value marker must be a finite number.')
            matches.append(value)
    if len(matches)!=1:raise Refused('LAS input needs one explicit missing-value marker.')
    return matches[0]
