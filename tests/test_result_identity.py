"""adhoc-e121-identity (E121 B10), offline: `deliver --item SLOT=@ASSET:REVISION` and `procedures run --item` bind
exactly that version when it is one the person can see, a pair that is not one is refused with the plain "no item"
sentence, and a name two items share is refused listing both, each with its version number and its @asset:revision.
The project is test_deliver's in-memory stand-in with a second item named "Tops"; the HTTP journey through the
installed wheel is the Platform's test_result_identity_e2e.py."""
import pytest

from ophiolite import procedures
from test_deliver import V1, V2, REV1, REV2, deliver, delivered_files, manifest, nothing_launched, world  # noqa: F401 (fixture)

REV3, V3 = '3' * 64, 'name,md\nNU,0\nNM,230\n'
BOTH = ('Not sent: more than one item you can see is named Tops: Tops version 2 (@tops-a:%s); Tops version 1 (@tops-b:%s). '
        'Name one as @ASSET:REVISION.' % (REV2, REV3))
FORMAT = 'Not sent: give each item as --item SLOT=NAME, --item SLOT=NAME@N (N its version number) or --item SLOT=@ASSET:REVISION.'


@pytest.fixture
def twice(world):
    world.add_item('tops-b', 'Tops', [(REV3, V3)])
    return world


@pytest.mark.parametrize('given,asset,revision,text', [('@tops-a:' + REV1, 'tops-a', REV1, V1), ('@tops-a:' + REV2, 'tops-a', REV2, V2),
                                                       ('@tops-b:' + REV3, 'tops-b', REV3, V3)])
def test_an_exact_version_is_delivered_though_two_items_share_its_name(twice, given, asset, revision, text):
    """Mutation: resolve the exact form by its item's name (or take the head) -> ambiguous, or the other version -> red."""
    w = twice
    answer = deliver(w, ['tops=' + given])
    assert answer['state'] == 'confirmed', answer
    assert delivered_files(w) == {f"{answer['delivery_id']}/tops-0.csv": text}
    assert w.posts[0]['refs'] == [{'project_id': 'p', 'asset_id': asset, 'revision': revision}]


@pytest.mark.parametrize('given', ['Tops', 'Tops@1'])
def test_a_name_two_items_share_is_refused_listing_both_to_copy(twice, given):
    """Mutation: restore the sentence without the candidates -> red."""
    with pytest.raises(procedures.NotRun) as refused: deliver(twice, ['tops=' + given])
    assert (refused.value.code, str(refused.value)) == ('item-ambiguous', BOTH)
    nothing_launched(twice)


@pytest.mark.parametrize('given', ['@tops-c:' + REV1, '@tops-a:' + REV3, '@tops-b:' + REV1])
def test_a_pair_that_is_not_a_version_you_can_see_gets_the_plain_no_item_sentence(twice, given):
    """An unknown asset, and a real asset with another item's revision, read the same: the sentence never says whether
    the pair exists. Mutation: drop the history check -> the read is tried with the wrong revision -> not item-missing."""
    with pytest.raises(procedures.NotRun) as refused: deliver(twice, ['tops=' + given])
    assert (refused.value.code, str(refused.value)) == ('item-missing', 'Not sent: there is no item named %s in this project that you can see.' % given)
    nothing_launched(twice)


@pytest.mark.parametrize('given', ['@tops-a', '@tops-a:', '@:' + REV1, '@tops-a:%s:x' % REV1])
def test_a_malformed_exact_form_is_refused_with_the_format_sentence(twice, given):
    with pytest.raises(procedures.NotRun) as refused: deliver(twice, ['tops=' + given])
    assert (refused.value.code, str(refused.value)) == ('item-format', FORMAT)
    nothing_launched(twice)


def test_run_items_share_the_resolver(twice, tmp_path):
    """`procedures run --from-project --item` reads its items with `_read_items`: the same exact binding and the same
    ambiguity sentence ("Not run:" there, from `_check_inputs`). Mutation: as above."""
    wanted = procedures._items(manifest(), ['tops=@tops-b:' + REV3, 'tops=@tops-a:' + REV1])
    assert wanted == [('tops', '@tops-b:' + REV3, None), ('tops', '@tops-a:' + REV1, None)]
    (tmp_path / 'scratch').mkdir()
    read = twice._read_items(wanted, tmp_path / 'scratch')
    assert [(slot, item['asset_id'], revision) for (slot, item, revision), _ in read] == [('tops', 'tops-b', REV3), ('tops', 'tops-a', REV1)]
    with pytest.raises(procedures.NotRun) as refused: twice._read_items(procedures._items(manifest(), ['tops=Tops']), tmp_path / 'again')
    assert str(refused.value) == BOTH
