"""Offline regression or holdout evaluation of the current production classifier."""
import argparse
import hashlib
import json
from pathlib import Path

from app.services import material_classification as production

TYPES = ('lecture', 'tutorial', 'other')
FIELDS = {'filename': 'filename', 'module_name': 'module_title', 'page_title': 'page_title',
          'link_title': 'link_text', 'nearby_text': 'nearby_text',
          'item_title': 'item_title', 'display_name': 'display_name'}


def load_gold(path, *, allow_empty=False):
    samples = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(samples, list) or (not samples and not allow_empty):
        raise ValueError('Gold dataset must be a non-empty JSON array.')
    seen = set()
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            raise ValueError(f'Sample {index + 1} must be an object.')
        sid = sample.get('sample_id')
        if not isinstance(sid, str) or not sid.strip() or sid in seen:
            raise ValueError(f'Sample {index + 1} needs a unique non-empty string sample_id.')
        seen.add(sid)
        if sample.get('expected_type') not in TYPES:
            raise ValueError(f'Sample {index + 1} has an invalid expected_type.')
        for field in FIELDS:
            if sample.get(field) is not None and not isinstance(sample[field], str):
                raise ValueError(f'Sample {index + 1}: {field} must be text or null.')
    return samples


def evaluate(samples, *, prediction_key='v2_1_prediction'):
    results = []
    for sample in samples:
        context = {target: sample.get(source) or '' for source, target in FIELDS.items()}
        # Same function and metadata names as production; no copied classification rules.
        prediction = production.classify_resource_type(**context).value
        results.append({'sample_id': sample['sample_id'], 'filename': context['filename'],
                        'expected_type': sample['expected_type'], prediction_key: prediction,
                        'correct': prediction == sample['expected_type']})
    correct = sum(row['correct'] for row in results)
    per_type = {}
    for role in TYPES:
        rows = [r for r in results if r['expected_type'] == role]
        hits = sum(r['correct'] for r in rows)
        per_type[role] = {'total': len(rows), 'correct': hits,
                          'accuracy': hits / len(rows) if rows else None}
    return {'total_samples': len(results), 'correct': correct, 'incorrect': len(results) - correct,
            'overall_accuracy': correct / len(results) if results else None,
            'per_type': per_type, 'results': results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True, type=Path)
    parser.add_argument('--split', choices=('regression', 'holdout'), default='regression',
                        help='Evaluate one dataset only; empty arrays are allowed for holdout.')
    parser.add_argument('--output', type=Path, help='Optional JSON report (use ignored data/ for real metadata).')
    args = parser.parse_args(argv)
    if args.output and args.output.resolve() == args.dataset.resolve():
        parser.error('Output must not overwrite the gold dataset.')
    try:
        samples = load_gold(args.dataset, allow_empty=args.split == 'holdout')
    except (OSError, ValueError) as error:
        parser.error(str(error))
    prediction_key = 'predicted_type' if args.split == 'holdout' else 'v2_1_prediction'
    report = evaluate(samples, prediction_key=prediction_key)
    report['split'] = args.split
    report['dataset_sha256'] = hashlib.sha256(args.dataset.read_bytes()).hexdigest()
    report['classifier_sha256'] = hashlib.sha256(Path(production.__file__).read_bytes()).hexdigest()
    label = 'Holdout' if args.split == 'holdout' else 'Development / Regression'
    print(f'Resource Classification - {label}\n')
    if not samples:
        print('No holdout samples available.\n')
    print(f"Total samples: {report['total_samples']}\nCorrect: {report['correct']}\nIncorrect: {report['incorrect']}")
    accuracy = 'N/A' if report['overall_accuracy'] is None else f"{report['overall_accuracy']:.2%}"
    print(f'\nOverall accuracy: {accuracy}')
    for role, metric in report['per_type'].items():
        percent = 'N/A' if metric['accuracy'] is None else f"{metric['accuracy']:.2%}"
        print(f"{role.title()}: {metric['correct']}/{metric['total']} ({percent})")
    print(f'\nsample_id\texpected_type\t{prediction_key}\tcorrect')
    for row in report['results']:
        print(f"{row['sample_id']}\t{row['expected_type']}\t{row[prediction_key]}\t{str(row['correct']).lower()}")
    for row in report['results']:
        if not row['correct']:
            print(f"\n[FAIL] {row['sample_id']}\nFilename: {row['filename']}\nExpected: {row['expected_type']}\nPredicted: {row[prediction_key]}")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0  # A measured classification error is a result, not an execution failure.


if __name__ == '__main__':
    raise SystemExit(main())
