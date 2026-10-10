"""Keep our team's LAS files as they are (an E105a sample procedure)."""
from ophiolite import procedure
from ophiolite.writers import WrittenOriginal


@procedure
def read(inputs, settings):
    source = inputs['file'][0]
    with open(source.path, 'rb') as handle:
        return {'log': WrittenOriginal(handle.read(), 'las2/1', {}, source.name)}
