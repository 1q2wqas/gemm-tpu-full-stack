# AI-Assisted OpenLane Backend

This folder contains the optimisation backend that accompanies the GEMM TPU
hardware project. The actual Python application is preserved inside
[`Major-Project--main/`](Major-Project--main/).

The backend runs an external OpenLane design, extracts physical-design metrics,
builds a structured prompt, asks an LLM for configuration changes, validates
those changes, and updates the external design's `config.json` before the next
iteration.

It is a separate workflow from [`../frontend/`](../frontend/). The checked-in
backend defaults to a design named `s1488`; using it for the TPU requires a
prepared TPU project in the OpenLane2 workspace and a corresponding change to
`Config/Settings.py`.
