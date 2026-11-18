# ForenSight AI

ForenSight AI is a workspace for recording forensic evidence handling conditions, reviewing preliminary contamination-risk indicators, and maintaining assessment history. Its rule-based assessment remains the primary screening mechanism. A separate experimental classifier demonstrates model training, tracking, serialization, and authenticated predictions.

> **Important limitation:** The experimental classifier uses generated examples and labels, not observed forensic outcomes. Neither the rule-based score nor the experimental output confirms that contamination occurred. This project is not a validated forensic decision system and does not measure real-world contamination detection.

## Architecture

- `app/main.py` starts FastAPI, initializes the existing SQLite database, loads the selected experimental artifact once during application startup, and serves the public website and authenticated workspace from `frontend/`.
- `app.py` provides a root-level application entry point by importing the FastAPI application from `app.main`.
- `static/index.html` provides a lightweight redirect to the main application interface. The actual frontend is served from `frontend/`.
- `app/routes.py` contains the authenticated assessment, history, dashboard, and combined-submission APIs. The original assessment schema and endpoints remain compatible; additional tables persist classifier execution results and request idempotency keys.
- `app/prediction_routes.py` exposes an authenticated, validated `POST /predict` endpoint separate from the rule-based assessment endpoints.
- The authenticated New Assessment form submits one request that records the primary rule-based screen and runs the experimental classifier. Classifier results are associated with the saved assessment; a failed classifier can be retried without creating another assessment.
- `app/services/risk_assessment.py` contains the primary preliminary rule-based assessment service.
- `app/services/synthetic_dataset.py` contains the reproducible simulated feature and outcome generator.
- `app/services/ml_experiments.py` validates data, normalizes features, and creates a grouped stratified split that keeps repeated feature profiles on one side of the train/test boundary.
- `train.py` compares Logistic Regression and Decision Tree configurations, logs results to MLflow, writes the comparison CSV, and serializes the selected pipeline.
- `app/services/model_runtime.py` loads and invokes the selected artifact.
- `app/services/prediction_logging.py` writes prediction inputs to JSON Lines.
- `app/services/check_drift.py` compares logged feature distributions with the simulated training set.
- `frontend/` contains the responsive public landing page and the existing authenticated workspace, built with HTML, CSS, and vanilla JavaScript. From the landing page, select **Open your workspace** to sign in or create an account.

## Dataset and outcome contract

Every target value is simulated. The labels are not observations from an external forensic dataset, verified laboratory outcomes, or labels derived from the rule-based assessment score.

The target distribution is:

| **Target value** | **Records** | **Share** |
|---|---:|---:|
| `synthetic_lower_risk` | 995 | 66.3% |
| `synthetic_higher_risk` | 505 | 33.7% |

| **Feature / target** | **Type** | **Allowed values / generation range** | **Why it matters** |
|---|---|---|---|
| `evidence_type` | Categorical string | `Biological`, `Trace`, `Digital`, `Firearms`, `Document`, `Other` | Identifies the category of evidence being assessed. |
| `collection_conditions` | Categorical string | `controlled`, `challenging`, `unknown` | Records whether collection conditions were controlled or potentially challenging. |
| `ppe_compliant` | Boolean | `true`, `false` | Indicates whether appropriate personal protective equipment compliance was confirmed. |
| `tool_condition` | Categorical string | `clean`, `compromised`, `unknown` | Records the condition of tools used during evidence collection. |
| `packaging_condition` | Categorical string | `intact`, `compromised`, `unknown` | Describes whether the primary evidence packaging is intact or potentially compromised. |
| `storage_condition` | Categorical string | `controlled`, `uncontrolled`, `unknown` | Records whether evidence storage conditions were controlled. |
| `separately_packaged` | Boolean | `true`, `false` | Indicates whether evidence was packaged separately to reduce possible contact or transfer. |
| `chain_of_custody_documented` | Boolean | `true`, `false` | Indicates whether evidence transfers and custody documentation are recorded. |
| `synthetic_outcome` | Classification target | `synthetic_lower_risk`, `synthetic_higher_risk` | Existing class identifiers for supervised model training and evaluation; the labels are generated, not observed forensic outcomes. |

The prediction API requires all eight input fields. Missing fields, unsupported categorical values, non-boolean values for boolean fields, and unexpected additional fields are rejected with HTTP 422. No numerical ranges apply because the contract contains no numerical feature.

### Simulated data-generation process

The generator samples each feature using fixed categorical probabilities:

- Evidence type: Biological 22%, Trace 19%, Digital 16%, Firearms 14%, Document 13%, Other 16%.
- Collection conditions: controlled 70%, challenging 22%, unknown 8%.
- PPE compliance: true 84%.
- Tool condition: clean 76%, compromised 18%, unknown 6%.
- Packaging condition: intact 78%, compromised 16%, unknown 6%.
- Storage condition: controlled 70%, uncontrolled 24%, unknown 6%.
- Separate packaging: true 78%.
- Chain-of-custody documentation: true 82%.

For each sampled record, the generator forms a simulated log-odds value `eta` starting at `-2.0`. It adds evidence-type offsets (Biological `+0.25`, Trace `+0.10`, Digital `-0.25`, Firearms `+0.15`, Document `-0.15`, Other `0`); challenging/unknown collection offsets `+0.75`/`+0.35`; PPE non-compliance `+0.70`; compromised/unknown tool offsets `+0.80`/`+0.30`; compromised/unknown packaging offsets `+0.75`/`+0.30`; uncontrolled/unknown storage offsets `+0.70`/`+0.25`; no separate packaging `+0.70`; and incomplete custody documentation `+0.65`. The generator adds `+0.30` for challenging collection with non-compliant PPE and `+0.35` for compromised packaging without separate packaging. It samples a binary outcome from `p = 1 / (1 + exp(-eta))`, then independently flips the label with probability `0.08`.

These are explicit simulation assumptions, not empirically estimated effects. The label-generation equation is independent from the rule-based scoring service.

Regenerate the same CSV with:

```bash
python -m app.services.synthetic_dataset
```

## Local setup

Requirements: Python 3.11 and pip.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Put the generated value in `.env` as `JWT_SECRET_KEY`. Do not commit `.env`. Use `COOKIE_SECURE=false` for local HTTP development; set it to `true` behind HTTPS. Start the application from the project root:

```powershell
python -m uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000/). FastAPI Swagger docs are at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). The SQLite application database defaults to `data/forensight.sqlite3`; `DATABASE_PATH` can override it.

## Model experiments, evaluation, and selection

The only trained algorithms are **Logistic Regression** and **Decision Tree**. Both use a scikit-learn pipeline with `OneHotEncoder(handle_unknown="ignore")`; the encoder is fitted only on training rows. No numeric scaler is needed for these categorical and boolean inputs. Both estimators use class-balanced weights and a fixed random state.

The experiment uses a reproducible four-fold `StratifiedGroupKFold` split (random state `42`). Each unique eight-feature profile is assigned wholly to either training or testing, preventing repeated profiles from crossing the boundary. The resulting split contains **1,125 training records and 375 test records**. Class labels are represented in both splits.

Run the four documented configurations and create the model artifact:

```powershell
python train.py `
  --lr-c-values 0.1 1.0 `
  --tree-depths 4 8 `
  --tree-min-samples-leaf 5 `
  --random-state 42 `
  --experiment-name forensight-csl236-final
```

The script supports these configuration arguments plus `--tracking-db`, `--model-path`, and `--comparison-path`. It logs each run's algorithm, hyperparameters, dataset metadata, training/testing counts, aggregate metrics, class-wise metrics, confusion matrix, and model artifact to an MLflow SQLite tracking store (`mlflow.db`). The generated `reports/experiment_comparison.csv` records the measured comparison.

Final measured results from the four configurations:

| **Run** | **Algorithm** | **Hyperparameters** | **Accuracy** | **Macro precision** | **Macro recall** | **Macro F1** |
|---|---|---|---:|---:|---:|---:|
| 01 | Logistic Regression | `C=0.1`, balanced, `max_iter=1000` | 0.6213 | 0.5867 | 0.5908 | 0.5878 |
| 02 | Logistic Regression | `C=1.0`, balanced, `max_iter=1000` | 0.5787 | 0.5602 | 0.5662 | 0.5570 |
| 03 | Decision Tree | `max_depth=4`, `min_samples_leaf=5`, balanced | 0.6240 | 0.5983 | 0.6062 | **0.5988** |
| 04 | Decision Tree | `max_depth=8`, `min_samples_leaf=5`, balanced | **0.6400** | 0.5930 | 0.5895 | 0.5908 |

The selected model is **Decision Tree (`max_depth=4`, `min_samples_leaf=5`)**, chosen by the highest macro F1; accuracy is the tie-breaker. The macro-F1 criterion gives equal weight to the two target classes. The deeper tree has higher accuracy but lower macro F1.

Selected model class-wise results on the 375-record test split:

| **Class** | **Precision** | **Recall** | **F1** | **Support** |
|---|---:|---:|---:|---:|
| `synthetic_lower_risk` | 0.7421 | 0.6613 | 0.6994 | 248 |
| `synthetic_higher_risk` | 0.4545 | 0.5512 | 0.4982 | 127 |

Confusion matrix (rows are actual; columns are predicted; class order is lower, higher):

| | **Predicted lower** | **Predicted higher** |
|---|---:|---:|
| Actual lower | 164 | 84 |
| Actual higher | 57 | 70 |

The held-out set was used to compare and select among configurations, so these metrics are exploratory and may be optimistic after selection. They do not constitute external validation. The dataset labels are generated, and these scores are not real-world forensic performance or contamination-detection accuracy. Future work would require a separately sourced and verified labeled dataset, group-aware external validation, and a pre-registered evaluation.

### MLflow

From the project root, view the SQLite-backed run history with:

```bash
mlflow ui --backend-store-uri sqlite:///mlflow.db --host 127.0.0.1 --port 5000
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000/). The default tracking database and `mlartifacts/` are local experiment outputs and are excluded from Git. Re-running `train.py` creates additional runs in the selected experiment.

### Model serialization and loading

The selected scikit-learn pipeline and evaluation metadata are saved with Joblib to `model/model.joblib`. The FastAPI lifespan loads this artifact once at application startup; prediction requests reuse the in-memory pipeline. Training and serving dependencies pin the same scikit-learn and Joblib versions. Only load this pickle-based artifact from a trusted project build; do not accept user-supplied Joblib files.

If the artifact is missing, the application still starts, `/health` reports `experimental_model_loaded: false`, and `/predict` returns HTTP 503 with an explicit error. A corrupt artifact fails startup visibly instead of silently falling back to another model.

## API

| **Method and path** | **Access** | **Purpose** |
|---|---|---|
| `GET /` | Public | Existing ForenSight web interface |
| `GET /health` | Public | Health and experimental model-loaded status only |
| `GET /docs` | Public | FastAPI Swagger UI |
| `POST /predict` | Authenticated + CSRF | Experimental classification using generated examples |
| `GET /api/auth/csrf` | Public | Issue CSRF token |
| `POST /api/auth/signup` | CSRF | Register and sign in |
| `POST /api/auth/login` | CSRF | Sign in |
| `POST /api/auth/logout` | CSRF | Sign out |
| `GET /api/auth/me` | Authenticated | Current account |
| `GET /api/dashboard` | Authenticated | Existing metrics and model evaluations |
| `GET/POST /api/assessments` | Authenticated | Assessment history / create rule-based assessment |
| `GET /api/assessments/{id}` | Authenticated | Read an owned assessment |
| `POST /api/assessments/workflow` | Authenticated + CSRF | Idempotently save one assessment and run its rule-based screen and experimental classifier |
| `GET /api/assessments/{id}/workflow` | Authenticated | Read the saved combined results |
| `POST /api/assessments/{id}/workflow/retry` | Authenticated + CSRF | Retry a failed experimental classifier for the existing assessment |

The `POST /predict` request uses the eight feature fields in the data-contract table. Example:

```json
{
  "evidence_type": "Trace",
  "collection_conditions": "controlled",
  "ppe_compliant": true,
  "tool_condition": "clean",
  "packaging_condition": "intact",
  "storage_condition": "controlled",
  "separately_packaged": true,
  "chain_of_custody_documented": true
}
```

The response contains the predicted class, per-class probabilities, selected algorithm, and a disclaimer. For API compatibility, the existing `dataset_type: "synthetic"` value and class identifiers remain unchanged. The New Assessment form runs this classifier alongside the primary rule-based screen and records the result against the saved assessment. Returned probabilities are model outputs, not calibrated real-world estimates.

The combined submission requires an `Idempotency-Key` header. Repeating the same request with the same key returns the existing assessment and results; reusing a key with different data is rejected. A separate retry endpoint re-runs only the failed classifier for the saved assessment.

Invalid examples return HTTP 422:

```json
{"evidence_type":"Trace","collection_conditions":"controlled"}
```

The example omits required fields. `"ppe_compliant": "true"` is also rejected because the API requires a JSON boolean, and an unsupported categorical value or any unexpected field is rejected. Invalid model input is never mapped to a default value.

## Existing rule-based screening and application

The existing authentication, SQLite assessment schema, scoring thresholds, explanations, recommendations, history, and analytics remain intact. Rule-based screening and experimental classifier outputs are shown as distinct results. The classifier result and execution status are stored in an additive workflow table, and the original assessment history endpoint remains unchanged.

## Prediction logging and drift checks

Each successful `/predict` request appends its feature inputs, UTC timestamp, and predicted class to `data/prediction_logs.jsonl`. It does not log passwords, tokens, account identifiers, or evidence reference IDs. The path can be overridden with `PREDICTION_LOG_PATH`. If writing fails, the application logs a warning and still returns the prediction.

Compare logged input distributions against the simulated training examples:

```bash
python -m app.services.check_drift
```

The checker reports per-feature share differences and flags an input distribution shift when the largest absolute category-share difference reaches the default threshold of `0.1` (override with `--threshold`). This is only a data-drift signal. It is not model performance degradation or an accuracy measurement; evaluating performance requires verified outcome labels.

## Testing

Install the full requirements, train the model, then run:

```powershell
python train.py
python -m pytest -v --tb=short
node --check frontend/app.js
```

The suite covers authentication, assessment, history, and dashboard behavior; dataset validation and reproducibility; grouped split separation; both model pipelines and metrics; serialization/loading and predictions; MLflow run logging; API health/UI; valid and invalid authenticated prediction requests; safe prediction logging; drift comparison; combined workflow persistence and idempotency; classifier retry without duplicate assessments; additive schema initialization; and removal of the authenticated Model Insights page.

Final local verification: **44 passed** with two dependency deprecation warnings (Starlette's TestClient/httpx adapter and MLflow/SQLAlchemy's `noload` strategy). `node --check frontend/app.js` also passed.

## Docker

The serving image uses `python:3.11-slim` and installs only `requirements-serve.txt`; MLflow, pytest, and training tools are excluded. Build and run locally in PowerShell:

```powershell
docker build -t forensight-ai .
$secret = python -c "import secrets; print(secrets.token_urlsafe(48))"
docker run --rm -p 8000:8000 -e JWT_SECRET_KEY=$secret -v "${PWD}\data:/app/data" forensight-ai
```

The API listens on `0.0.0.0:8000`. The volume keeps the SQLite application data and prediction log outside the container. Run the server only behind an appropriately configured HTTPS reverse proxy for non-local use.

### Docker verification results

The Docker image was successfully built using `python:3.11-slim` and `requirements-serve.txt`.

**Verified locally on 13 November 2026:**

| **Check** | **Result** |
|---|---|
| Docker image build | Successful |
| Image tag | `forensight-ai:latest` |
| Docker disk usage | 592 MB |
| Image content size | 136 MB |
| Container startup | Successful |
| Health endpoint | HTTP 200 |
| Experimental model loading | Successful |
| Application UI | Loaded |
| Signup and login | Successful |
| Valid experimental prediction | Successful |
| Invalid prediction input | HTTP 422 |

The container was tested using host port `8001`, mapped to container port `8000`. The `/health` endpoint returned `status: ok` and `experimental_model_loaded: true`.

The invalid prediction test confirmed that an unsupported `evidence_type` is rejected with HTTP 422 while authentication and CSRF protections remain enabled.

These results verify local Docker execution. The production application is hosted at https://forensightai-1.onrender.com.

## GitHub Actions

The project uses GitHub Actions for automated continuous integration.

The workflow is defined in `.github/workflows/ci.yml` and runs automatically on:

- Pushes to the `main` branch.
- Pull requests targeting the `main` branch.

The workflow performs the following steps:

1. Checks out the repository.
2. Sets up Python 3.11 and Node.js 22.
3. Installs the project dependencies.
4. Trains the baseline machine-learning model.
5. Validates frontend JavaScript syntax.
6. Executes the automated test suite using `python -m pytest -v --tb=short`.

**CI verification:** The GitHub Actions workflow completed successfully, and the latest commit displays a green check mark on GitHub.

## Security and privacy

- Passwords use Argon2id hashing; JWT secrets come from environment variables.
- Authentication uses expiring HS256 JWTs in `HttpOnly`, `SameSite=Strict` cookies; unsafe requests require CSRF validation.
- Protected records and prediction requests require an authenticated account.
- `.env`, the local application database, MLflow database/artifacts, prediction logs, and Python caches are excluded from Git.
- The project source code has been pushed to the GitHub repository.

## Limitations and future work

The generator encodes assumed relationships, and the model learns generated labels rather than verified contamination outcomes. The reported holdout results are exploratory, come from a single split also used for configuration selection, and must not be interpreted as forensic accuracy. The rule-based score is still preliminary and separate. A future study would need accessible, ethically and legally governed forensic data with verified outcome labels, group-aware independent evaluation, expert review, and documented deployment monitoring before any real-world claims.
