"""Quantify's independently trained topic classifier; no Qwen or network calls.

Multinomial naive Bayes over words and word pairs. Small, interpretable baseline;
topic scores are not calibrated confidence or predicted stock returns.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re

LABELS = ["Analyst Update", "Fed | Central Banks", "Company | Product News",
    "Treasuries | Corporate Debt", "Dividend", "Earnings", "Energy | Oil", "Financials",
    "Currencies", "General News | Opinion", "Gold | Metals | Materials", "IPO",
    "Legal | Regulation", "M&A | Investments", "Macro", "Markets", "Politics",
    "Personnel Change", "Stock Commentary", "Stock Movement"]
DEFAULT_PATH = Path(__file__).parent / "instance" / "news_topic_model.json"


def words(text):
    text = re.sub(r"https?://\S+", " ", text.lower())
    return re.findall(r"[a-z][a-z'-]{1,}", text)


def features(text):
    tokens = words(text)
    return tokens + [a + " " + b for a, b in zip(tokens, tokens[1:])]


def predict(model, text):
    counts = Counter(features(text))
    scores = model["priors"][:]
    known = 0
    # U distinct features × C topics, not U². C is fixed at 20; these sums
    # are the classifier itself, not repeated comparisons between articles.
    for token, count in counts.items():
        weights = model["weights"].get(token)
        if weights is not None:
            known += count
            for i, weight in enumerate(weights):
                scores[i] += count * weight
    if known < 2:
        return {"status": "insufficient_vocabulary", "topic": None, "model": "quantify-news-nb-v1"}
    # Only two results are needed. One pass preserves label-order tie breaking.
    best, runner_up = (0, 1) if scores[0] >= scores[1] else (1, 0)
    for i in range(2, len(scores)):
        if scores[i] > scores[best]:
            best, runner_up = i, best
        elif scores[i] > scores[runner_up]:
            runner_up = i
    return {"status": "classified", "topic": LABELS[best],
        "alternative": LABELS[runner_up], "model": "quantify-news-nb-v1",
        "training_id": model["training_id"], "confidence": "not calibrated"}


@lru_cache(maxsize=1)
def load_model(path, modified):
    return json.loads(Path(path).read_text())


def classify(text, path=DEFAULT_PATH):
    path = Path(path)
    try:
        return predict(load_model(str(path), path.stat().st_mtime_ns), text)
    except (OSError, ValueError, KeyError):
        return {"status": "model_unavailable", "topic": None, "model": "quantify-news-nb-v1"}


def read_rows(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        rows = []
        for row in csv.DictReader(stream):
            label = int(row["label"])
            if not 0 <= label < len(LABELS):
                raise ValueError("Unknown topic label")
            if words(row["text"]):
                rows.append((row["text"], label))
        return rows


def train(train_path, valid_path, output):
    training, validation = read_rows(train_path), read_rows(valid_path)
    # Remove all conflicting duplicates, then keep one copy of each training text.
    labels_by_text = {}
    for text, label in training:
        labels_by_text.setdefault(" ".join(words(text)), set()).add(label)
    unique = {}
    for text, label in training:
        key = " ".join(words(text))
        if len(labels_by_text[key]) == 1:
            unique[key] = (text, label)
    document_frequency = Counter()
    for text, _ in unique.values():
        document_frequency.update(set(features(text)))
    vocabulary = {token for token, n in document_frequency.most_common(20000) if n >= 2}
    counts = [Counter() for _ in LABELS]
    classes = Counter()
    for text, label in unique.values():
        classes[label] += 1
        counts[label].update(token for token in features(text) if token in vocabulary)
    if len(classes) != len(LABELS):
        raise ValueError("Training needs examples for all 20 topics.")
    totals = [sum(c.values()) + len(vocabulary) for c in counts]
    weights = {token: [math.log((counts[i][token] + 1) / totals[i]) for i in range(len(LABELS))]
               for token in sorted(vocabulary)}
    checksum = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
    train_checksum = checksum(train_path)
    model = {"version": 1, "training_id": train_checksum[:16],
        "priors": [math.log(classes[i] / len(unique)) for i in range(len(LABELS))],
        "weights": weights}
    # The report uses only per-class totals, not pairwise confusion counts.
    actual_counts = [0] * len(LABELS)
    predicted_counts = [0] * len(LABELS)
    correct_counts = [0] * len(LABELS)
    label_indices = {label: i for i, label in enumerate(LABELS)}
    seen = set(labels_by_text)
    skipped = abstained = 0
    for text, label in validation:
        key = " ".join(words(text))
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        result = predict(model, text)
        if result["topic"] is None:
            abstained += 1
        else:
            predicted = label_indices[result["topic"]]
            actual_counts[label] += 1
            predicted_counts[predicted] += 1
            correct_counts[label] += int(label == predicted)
    per_class = []
    for i, label in enumerate(LABELS):
        tp = correct_counts[i]
        predicted = predicted_counts[i]
        actual = actual_counts[i]
        per_class.append({"topic": label, "support_classified": actual,
            "f1": 2 * tp / (predicted + actual) if predicted + actual else 0})
    evaluated = sum(actual_counts) + abstained
    metrics = {"training_examples": len(unique), "validation_examples": evaluated,
        "validation_duplicates_removed": skipped, "abstained": abstained,
        "accuracy": sum(correct_counts) / evaluated if evaluated else None,
        "macro_f1_classified": sum(row["f1"] for row in per_class) / len(LABELS),
        "majority_baseline": max(actual_counts) / evaluated if evaluated else None,
        "per_class": per_class, "vocabulary": len(vocabulary),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "https://huggingface.co/datasets/zeroshot/twitter-financial-news-topic",
        "dataset_license": "MIT per dataset card; underlying content rights require separate review for redistribution",
        "train_sha256": train_checksum, "validation_sha256": checksum(valid_path),
        "limitations": "Topic classification only. Provider validation split is not chronological. "
            "Exact normalized duplicates removed; near-duplicate events may remain. "
            "Performance on current BBC/CNBC news is unmeasured. No return or trading accuracy claim."}
    model["metrics"] = metrics
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(model, separators=(",", ":")))
    temporary.replace(output)
    output.with_suffix(".metrics.json").write_text(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("training_csv")
    parser.add_argument("validation_csv")
    parser.add_argument("--output", default=str(DEFAULT_PATH))
    args = parser.parse_args()
    print(json.dumps(train(args.training_csv, args.validation_csv, args.output), indent=2))
