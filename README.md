# Automated Flaky Test Detection Pipeline for iDFlakies, NonDex, and FlakeSync
###### Originally Authored By: Your favorite loaf, Loafyy
###### Contributors: Samuel Song

## 📌 Overview
This repository provides an automated, scalable GitHub Actions pipeline designed to detect flaky tests across **Maven-based Java 8 projects** in the IDoFT dataset (`pr-data.csv`).
It runs **10 rounds each** of two detection tools: **iDFlakies** and **NonDex** along with **FlakeSync** via standalone CLI commands without modifying the `pom.xml` or other features of the projects.
After each run, results are parsed and aggregated into a clean set of csv files: one for iDFlakies, NonDex, and FlakeSync.

### ⚠️ DISCLAIMER
As this is an automated process, tests *will* be missed due to version mismatches, missing/undetected `pom.xml`, or other factors.

---

## ⚙️ How It Works

1. **Dynamic Matrix Generation:**
   * A pre-processing Python script (`generate_matrix.py`) reads `pr-data.csv` and builds a parallel GitHub Actions matrix.
   * Supports pagination (`max_projects` and `offset` inputs) to easily process specific batches or chunks of the dataset.

2. **Flaky Test Tooling Execution:**
   * **iDFlakies (`idflakies-maven-plugin:2.0.0`):** Shuffles test class and method execution orders (`random-class-method`) to uncover Order-Dependent (OD) test flakiness.
   * **NonDex (`nondex-maven-plugin:2.2.1`):** Explores non-deterministic iteration orders in underlying Java collection APIs (e.g., `HashMap`, `HashSet`) to detect Implementation-Dependent (ID) flakiness.
   * **FlakeSync (`flakesync-maven-plugin:1.0-SNAPSHOT`):** Injects artificial thread delays via condition-based execution sweeps to target race conditions and identify Timing-Dependent (TD) async flakiness.

3. **Recursive Parsing & Artifact Aggregation:**
   * Downstream jobs automatically collect generated artifacts, including hidden dot-directories (`.dtfixingtools`, `.nondex`).
   * A sanitizing script (`aggregate_results.py`) recursively searches detection logs, filters out stack traces and build log noise using strict Java identifier regex, and writes clean results.

---

## 📊 Summary Output Format

The workflow outputs three aggregated CSV artifacts:
* `idflakies_summary.csv`
* `nondex_summary.csv`
* `flakesync_td_tests.csv`

Each CSV strictly adheres to the following 3-column format:

| project_name | sha | flaky_test |
| :--- | :--- | :--- |
| `repo` | `1764748eedb2f320a0d1c43cb4f928c4ccb1f2f5` | `com.example.pkg.MyTest.testMethod` |

*Except flaksync, which adds a location column.*

---

## 🚀 Usage Guide:
This repo requires minimal setup and zero YAML config editing.

### Step 1: Fork This Repository
This will allow you to have your own space to run your tests.
> **Note for Forks:** When running in a newly forked repository, go to the **Actions** tab and click **"I understand my workflows, go ahead and enable them"** to enable execution.


### Step 2: Go to ACTIONS Tab on GitHub
This should take you to a screen where you can select workflows.  
Select `Dynamic Flaky Test Detection Pipeline` from the LEFT side of the screen.  

<img width="608" height="67" alt="image" src="https://github.com/user-attachments/assets/e9396d8b-3570-49a6-b369-c91df039e00d" />


*Actions Tab*

<img width="393" height="112" alt="image" src="https://github.com/user-attachments/assets/699b2d8b-9b94-4db9-9e8a-c6a5639ef7ad" />


*Workflow Selection*

### Step 3: Select <Run Workflow> and Choose Appropriate Parameters
The number of tests you can run concurrently may be limited! As such there is an offset parameter so you can choose different tests to run.

<img width="422" height="497" alt="image" src="https://github.com/user-attachments/assets/841e52a9-4b0b-49c3-9f01-090f348c605e" />

### Step 4: Run and Wait for Results!
The artifacts from this automated pipeline will appear after the workflow is complete.  

<img width="2002" height="458" alt="image" src="https://github.com/user-attachments/assets/7755b4e3-4732-4a8b-af5f-04268f80e279" />

