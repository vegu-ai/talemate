## ChromaDB

If you want chromaDB to use the more accurate (but much slower) instructor embeddings add the following to `config.yaml`:

```yaml
chromadb:
    embeddings: instructor
    instructor_device: cpu
    instructor_model: hkunlp/instructor-xl"
```

You will need to restart the backend for this change to take effect.

### GPU support

If you want to use the instructor embeddings with GPU support, you will need to install pytorch with CUDA support. 

To do this on windows, run `install-pytorch-cuda.bat` from the project root. Then change your device in the config to `cuda`:

```yaml
chromadb:
    embeddings: instructor
    instructor_device: cuda
    instructor_model: hkunlp/instructor-xl"
```

Instructor embedding models:

- `hkunlp/instructor-base` (smallest / fastest)
- `hkunlp/instructor-large` 
- `hkunlp/instructor-xl` (largest / slowest) - requires about 5GB of GPU memory