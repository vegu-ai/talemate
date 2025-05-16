# 4 - Agentic Workflow

In part 3 we left off at generating a random story premise for the crew of the Starlight Nomad.

To recap - We are using the `Creator` agent to generate a list of sci-fi topics and then picking a random one to inform the generation of the introduction.

We can leverage additional agents to further improve the quality of the introduction.

Generally speaking, one of the biggest improvements of quality I've personally seen is when an instruction is first separately analyzed and clarified by a more analytical agent like the Summarizer or the Director.

For example, if we get the theme "Solar flare storms", we could ask the `Summarizer` to analyze and brainstorm what to do with the theme, before we clarify it into an instruction to give to the `Creator` agent.