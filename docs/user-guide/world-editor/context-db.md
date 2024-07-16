# Context DB

A very rudimentary interface to browse the current context database managed by the [Memory Agent](/user-guide/agents/memory/).

!!! note
    This interface will likely be revamped soon, so documentation will be minimal currently.

## Searching

Search is done by typing in the search field and pressing `Enter`.

The search will look for the entered text based on relevancy using embeddings. Without getting too technical here, that means if you're using the basic chromadb configuration, accuracy may be lacking.

See [Memory Agent - ChromaDB Setup](/user-guide/agents/memory/chromadb) for more information on how to improve the search accuracy.

![world editor history](/talemate/img/0.26.0/world-editor-history.png)

## Adding an entry

While you can manually add an entry through this interface, its not really encouraged anymore.

It is better to use the :material-earth: **World** and :material-account-group: **Characters** tabs to add entries to the context database.

## Tools

### Reset

Resets the context database, and will remove all entries and then re-populate it with the entries in the current scene.

!!! warning
    Entries added manually directly to the context db will not be in the scene file, and be lost during this operation.