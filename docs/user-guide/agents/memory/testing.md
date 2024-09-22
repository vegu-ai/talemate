# Testing Embeddings

You can test the performance of the selected embedding, by using talemate normally and then inspecting the memory request in the debug tools view.

![Open debug tools](/talemate/img/0.27.0/open-debug-tools.png)

Once the debug tools are open, select the :material-processor: Memory tab.

Then wait for the next talemate generation (for example conversation) and all the memory requests will be shown in the list.

![Testing memory 1](/talemate/img/0.27.0/testing-memory-1.png)

In this particular example we are asking Kaira when we first met, and the expectation is for the memory agent to find and return the memory of the first meeting.

Click the memory request to see the details.

![Testing memory 2](/talemate/img/0.27.0/testing-memory-2.png)

Up to 10 results are shown, however only those that fall within the acceptable distance are included in the context. 

Selected entries will have their distance function colored green, while the others will be going from yellow to red.

If you find that accuracy is lacking you may need to tweak the [Embedding settings](/talemate/user-guide/agents/memory/embeddings).