# Score Studio MuScriptor Worker

CPU-only MuScriptor worker used by the Score Studio test service.

- Model: `small`
- Device: CPU
- HTTP healthcheck: `/health`
- Transcription endpoint: `/transcribe` and `/transcribe/midi`

The model weights require Hugging Face access to the MuScriptor model license.
