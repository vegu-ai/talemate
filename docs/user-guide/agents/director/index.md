# Overview

The director agent serves as the game master for your scenes, guiding story progression and helping manage the creative experience. It provides several key features that work together to enhance your storytelling.

## Features

### Autonomous Scene Direction

!!! info "New in 0.35.0"
    Autonomous Scene Direction replaces the previous Auto Direction feature with a more capable implementation.

Allows the director to autonomously progress your scene using the same actions available through Director Chat. The director analyzes the scene context and decides when and how to move the story forward.

A strong LLM (100B+) with reasoning capabilities is highly recommended for best results.

See the [Autonomous Scene Direction](/talemate/user-guide/agents/director/scene-direction) page for detailed information.

### Director Chat

A conversational interface for interacting with the director directly. You can ask questions, request changes, and guide story progression through natural language.

See the [Director Chat](/talemate/user-guide/agents/director/chat) page for more information.

### Dynamic Actions

Generates clickable choices for the user during scene progression. This allows you to make decisions that affect the scene or story without manually typing out your choice.

### Guide Scene

Uses the summarizer agent's scene analysis to guide characters and the narrator for the next generation, helping improve the quality and coherence of generated content.