# ChromaDB

Talemate uses ChromaDB to maintain long-term memory. The default embeddings used are really fast but also not incredibly accurate. If you want to use more accurate embeddings you can use the instructor embeddings or the openai embeddings. See below for instructions on how to enable these.

In my testing so far, instructor-xl has proved to be the most accurate (even more-so than openai)

## Local instructor embeddings

If you want chromaDB to use the more accurate (but much slower) instructor embeddings add the following to `config.yaml`:

**Note**: The `xl` model takes a while to load even with cuda. Expect a minute of loading time on the first scene you load.

```yaml
chromadb:
    embeddings: instructor
    instructor_device: cpu
    instructor_model: hkunlp/instructor-xl
```

### Instructor embedding models

- `hkunlp/instructor-base` (smallest / fastest)
- `hkunlp/instructor-large` 
- `hkunlp/instructor-xl` (largest / slowest) - requires about 5GB of memory

You will need to restart the backend for this change to take effect.

**NOTE** - The first time you do this it will need to download the instructor model you selected. This may take a while, and the talemate backend will be un-responsive during that time.

Once the download is finished, if talemate is still un-responsive, try reloading the front-end to reconnect. When all fails just restart the backend as well. I'll try to make this more robust in the future.

### GPU support

If you want to use the instructor embeddings with GPU support, you will need to install pytorch with CUDA support. 

To do this on windows, run `install-pytorch-cuda.bat` from the project directory. Then change your device in the config to `cuda`:

```yaml
chromadb:
    embeddings: instructor
    instructor_device: cuda
    instructor_model: hkunlp/instructor-xl
```

## OpenAI embeddings

First make sure your openai key is specified in the `config.yaml` file

```yaml
openai:
  api_key: <your-key-here>
```

Then add the following to `config.yaml` for chromadb:

```yaml
chromadb:
    embeddings: openai
    openai_model: text-embedding-3-small
```

**Note**: As with everything openai, using this isn't free. It's way cheaper than their text completion though. Always monitor your usage on their dashboard.
