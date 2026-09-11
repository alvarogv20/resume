# Álvaro Garrido — Engineering CV

Based on [Jake Gutierrez's resume](https://github.com/jakegut/resume), retaining the MIT license and original `resume.tex` and `resume.png` as upstream references.

## Files

- `base.tex`: general engineering CV.
- `airbus-4448452505.tex`: Airbus Flight Physics PMTD application draft.
- `layout.tex`: shared single-column A4 layout with sequential job/date lines and Unicode fonts.
- `roles/airbus-4448452505.md`: requirements, evidence and gaps.
- `contact.example.tex`: example for the local-only contact block.

## Build

Install [Tectonic](https://tectonic-typesetting.github.io/). From the repository root:

```sh
mkdir -p build
tectonic --outdir build base.tex
tectonic --outdir build airbus-4448452505.tex
```

Tectonic downloads required TeX packages on its first run. XeLaTeX can also compile these files.
Copy `contact.example.tex` to `contact.tex` and replace its placeholders for a complete local PDF. `contact.tex` and `build/` are ignored by Git, keeping direct contact details and completed PDFs out of the public fork. Without that file the heading contains only Madrid, Spain.

## Another position

### Automated workflow

The editable source of truth is now `profile/profile.yaml`. See
[the automation guide](docs/automation.md) for local Codex generation, private
contacts, evidence validation and optional Actions in a private automation repository.

- [Workflow and tools](docs/workflow.md)
- [Provider configuration and API examples](docs/configuration.md)
- [Resume and troubleshooting](docs/troubleshooting.md)

Codex is the default. OpenAI Responses and explicitly configured Chat Completions
compatible APIs share the same evidence checks. PowerShell and Actions accept provider
and model overrides; there is no automatic provider fallback.

```sh
python -m pip install -r requirements.txt
python -m automation.run --url "https://www.linkedin.com/jobs/view/JOB_ID/" --slug company-job-id --language en
```

Configure `.private/contact.json` from `contact.example.json` first. Final PDFs
include email, phone and LinkedIn but stay in the ignored `build/` directory.
Public results contain only contact-free LaTeX and the evidence analysis. The
pipeline never updates the master profile or submits applications automatically.

### Manual workflow

Copy `base.tex` to a role-specific file, record the job link and evidence in `roles/`, then reorder and rewrite supported experience. Preserve dates, titles and achievements. Do not invent certifications, durations or skills.

Compile, inspect page layout and extract PDF text before submission. Readable text does not guarantee ATS selection. Follow the employer's requested file type.

The owner accepted the existing profile as the editable master in September 2026.
Record future revisions in `profile/evidence.md`. This repository prepares documents;
it does not submit applications.
