import warnings
from pathlib import Path
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from sklearn.svm import SVC

warnings.filterwarnings("ignore")

def check_classical_baseline(project_dir: Path, manifest: dict) -> dict:
    baselines = manifest.get("classical_baselines", [])
    if not baselines:
        return {"status": "SKIPPED", "best_accuracy": None, "details": "No classical baselines declared."}

    data_config = manifest.get("inputs", {})
    dataset_path = project_dir / data_config.get("dataset", {}).get("path", "")
    
    df = pd.read_csv(dataset_path)
    target_col = data_config.get("target_column")
    X = df.drop(columns=[target_col])
    y = df[target_col]
    
    split_config = data_config.get("train_test_split", {})
    test_size = split_config.get("test_size", 0.2)
    seed = split_config.get("random_seed", 1729)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=test_size, random_state=seed)
    
    best_acc = 0.0
    best_model = None

    for model_cfg in baselines:
        algo = model_cfg.get("algorithm")
        if algo == "rbf_svm":
            clf = SVC(kernel="rbf", gamma="scale")
        elif algo == "logistic_regression":
            clf = LogisticRegression()
        elif algo == "random_forest":
            clf = RandomForestClassifier(random_state=seed)
        else:
            continue
            
        clf.fit(X_train, y_train)
        acc = accuracy_score(y_test, clf.predict(X_test))
        if acc > best_acc:
            best_acc = acc
            best_model = algo
            
    contract = manifest.get("contract", {})
    min_required = contract.get("minimum_test_accuracy", 0.0)
    
    if best_acc >= min_required:
        status = "CLASSICAL_BASELINE_MEETS_CONTRACT"
        details = f"Classical {best_model} achieved {best_acc*100:.1f}%. Quantum contract minimum is {min_required*100:.1f}%."
    else:
        status = "PASS"
        details = f"Classical models failed to reach minimum accuracy ({best_acc*100:.1f}% vs {min_required*100:.1f}%)."

    return {"status": status, "best_accuracy": best_acc, "best_model": best_model, "details": details}
