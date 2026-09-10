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

Copy `base.tex` to a role-specific file, record the job link and evidence in `roles/`, then reorder and rewrite supported experience. Preserve dates, titles and achievements. Do not invent certifications, durations or skills.

Compile, inspect page layout and extract PDF text before submission. Readable text does not guarantee ATS selection. Follow the employer's requested file type.

Source CV last updated March 2026. Confirm current employment and contacts before applying. This repository prepares documents; it does not submit applications.
