# Automated Flaky Test Detection Pipeline for iDFlakies and NonDex
###### By: Your favorite loaf, Loafyy


## Overall Summary of What This Automated Pipeline Does
This pipeline takes data in `pr-data.csv` from the IDoFT repo and takes all *unique* project and SHA entries. It then feeds these entries and creates a matrix that is usable by github workflows to run iDFlakies and NonDex automatically on a repository. If there are any errors, please let me know. The yaml currently accounts for `JDK 17` and `JDK 8` projects only! Projects or SHAs with other versions of Java may be skipped entirely!

### DISCLAIMER
As this is an automated process, there is a chance that some tests are missed! That being said, most should be recorded properly! Best of luck detectors, and I hope this kit finds you well.

## Usage Guide:
This repo requires minimal setup. Parameters may be edited in the `yml` (yaml) file found in `.github/`.

### Step 1: Fork or Clone This Repository
This will allow you to have your own space to run your tests.

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
The artifacts we are looking for are `idflakies_summary_csv` and `nondex_summary_csv`.

<img width="2062" height="548" alt="image" src="https://github.com/user-attachments/assets/dd4cfa2c-91f6-4cd1-9a40-6495d4ae8d8b" />
