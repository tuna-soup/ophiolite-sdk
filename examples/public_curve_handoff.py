"""Local calculation using public SDK methods only; no private kit or services."""
import argparse
import os
from pathlib import Path
from ophiolite import Client, Credential


def calculate(client, folder, asset, revision, curve):
    work = client.work_folder(folder)
    binding = work.configure(asset, revision, curve=curve, name='Local curve calculation')
    run = work.start(binding, application_version='public-curve-handoff/1',
                     parameters={'operation':'multiply', 'factor':2},
                     script=Path(__file__).read_bytes())
    original, view = run.input()
    # Preserve missing values and the exact axis; multiplication preserves units.
    values = [None if value is None else value * 2 for value in view.values]
    receipt = work.publish(run, derived_curves=[{
        'mnemonic':'CALC', 'unit':view.unit,
        'description':'Original selected values multiplied by two', 'values':values,
    }])
    work.download(receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asset', required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--curve', required=True)
    parser.add_argument('--work', required=True)
    args = parser.parse_args()
    credential = Credential.bearer(os.environ['OPHIOLITE_TOKEN'], grant=os.environ.get('OPHIOLITE_GRANT'))
    with Client(os.environ['OPHIOLITE_URL'], os.environ['OPHIOLITE_PROJECT'], credential) as client:
        calculate(client, args.work, args.asset, args.revision, args.curve)
    print('Result saved. Sharing is unchanged; inspect the receipt in your work folder.')


if __name__ == '__main__':
    main()
