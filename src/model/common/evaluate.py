import numpy as np
import torch
import torch.nn.functional as F


def predict_logits(head, X, batch=256):
    head.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(X), batch):
            out.append(head(torch.from_numpy(X[i:i + batch].astype(np.float32))))
    return torch.cat(out)


def compute_metrics(logits, y, classes):
    y_t = torch.from_numpy(np.asarray(y, np.int64))
    loss = float(F.cross_entropy(logits, y_t))
    pred = logits.argmax(dim=1).numpy()
    y = np.asarray(y, np.int64)
    k = len(classes)
    cm = np.zeros((k, k), np.int64)
    for t, p in zip(y, pred):
        cm[t, p] += 1
    per_class = {}
    for i, name in enumerate(classes):
        tp = int(cm[i, i])
        fp = int(cm[:, i].sum() - tp)
        fn = int(cm[i, :].sum() - tp)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[name] = {'precision': precision, 'recall': recall, 'f1': f1, 'support': int(cm[i, :].sum())}
    return {
        'loss': loss,
        'accuracy': float((pred == y).mean()),
        'macro_f1': float(np.mean([v['f1'] for v in per_class.values()])),
        'per_class': per_class,
        'confusion_matrix': cm.tolist(),
    }


def evaluate(head, X, y, classes):
    return compute_metrics(predict_logits(head, X), y, classes)
