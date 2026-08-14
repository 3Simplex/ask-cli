# Mermaid Diagram Guide

Mermaid is a JavaScript library that allows you to create diagrams and flowcharts using a simple text-based syntax. This guide covers how to use Mermaid CLI on NixOS.

## Installation

Install Mermaid CLI via Nix:

    nix shell nixpkgs#mermaid-cli

## Quick Reference: The `--command bash -c` Wrapper

Mermaid CLI is a Node.js package. The `nix shell` command only puts the wrapper script on PATH, not the actual `mmdc` binary. You **must** use `--command bash -c` to invoke it correctly.

### ❌ This won't work — mmdc isn't in PATH

    nix shell nixpkgs#mermaid-cli --command mmdc -i input.mmd -o output.png -e png

### ✅ Correct — must wrap through bash

    nix shell nixpkgs#mermaid-cli --command bash -c 'mmdc -i input.mmd -o output.png -e png'

## Basic Usage

### Generate a PNG image

    nix shell nixpkgs#mermaid-cli --command bash -c 'mmdc -i input.mmd -o output.png -e png'

### Generate an SVG image

    nix shell nixpkgs#mermaid-cli --command bash -c 'mmdc -i input.mmd -o output.svg -e svg'

### Generate a PDF image

    nix shell nixpkgs#mermaid-cli --command bash -c 'mmdc -i input.mmd -o output.pdf -e pdf'

### Read from stdin

    echo 'graph TD; A --> B' | nix shell nixpkgs#mermaid-cli --command bash -c 'mmdc -i - -o output.png -e png'

## Mermaid Syntax

### Graph Types

- graph TD — Top-to-bottom directed graph
- graph LR — Left-to-right directed graph
- graph TB — Top-to-bottom (same as TD)
- graph FL — Flowchart (left-to-right)
- graph UML — UML-style diagram
- sequenceDiagram — Sequence diagram
- classDiagram — Class diagram
- stateDiagram — State diagram
- flowchart — Flowchart (same as graph)

### Node Styles

    style A fill:#f9f,stroke:#333,stroke-width:2px
    style B fill:#ff9,stroke:#333,stroke-width:2px
    style C fill:#bbf,stroke:#333,stroke-width:2px

### Subgraphs

    subgraph "Title"
        A --> B
    end

### Decision Nodes

    B -->|Yes| C
    B -->|No| D

### Comments

    %% This is a comment

## Common Pitfalls

1. **Parentheses in node labels**: Mermaid CLI's parser can fail on parentheses in node labels. Use square brackets instead:
   - BAD: A[func(args)]
   - GOOD: A[func args]

2. **Newlines in node labels**: Use backslash-n for line breaks:
   - GOOD: A[Line 1\nLine 2]

3. **Pipe characters**: Use pipe for decision branches:
   - GOOD: B -->|Yes| C

4. **Quotes in labels**: Use double quotes for subgraph titles:
   - GOOD: subgraph "Title"

5. **File encoding**: Ensure files are saved as UTF-8.

6. **Output file location**: Files are written to your current working directory, not your home directory.
   ```
   nix shell nixpkgs#mermaid-cli --command bash -c 'mmdc -i input.mmd -o output.png -e png'
   ls output.png  # ✅ Found here
   ```

## Example: State Guard Evaluator

    graph TD
        A[Input: target_state] --> B{Stateful?}
        B -->|Yes| C[Fetch eval_msgs from last 5 messages]
        B -->|No| D[No history]
        C --> E[Build history_text]
        D --> E
        E --> F[Construct System Prompt]
        F --> G[Construct User Prompt]
        G --> H[Call llm_eval_call]
        H --> I[POST to LLM API]
        I --> J[Parse JSON Response]
        J --> K{passed == true?}
        K -->|Yes| L[EvalResult: PASS]
        K -->|No| M[EvalResult: FAIL]
        L --> N[Agent enters state]
        M --> O[Agent blocked from state]
        N --> P[Next state transition]
        O --> P
        style A fill:#f9f,stroke:#333,stroke-width:2px
        style B fill:#ff9,stroke:#333,stroke-width:2px
        style C fill:#bbf,stroke:#333,stroke-width:2px
        style D fill:#bbf,stroke:#333,stroke-width:2px
        style E fill:#bbf,stroke:#333,stroke-width:2px
        style F fill:#bbf,stroke:#333,stroke-width:2px
        style G fill:#bbf,stroke:#333,stroke-width:2px
        style H fill:#bbf,stroke:#333,stroke-width:2px
        style I fill:#bbf,stroke:#333,stroke-width:2px
        style J fill:#bbf,stroke:#333,stroke-width:2px
        style K fill:#ff9,stroke:#333,stroke-width:2px
        style L fill:#9f9,stroke:#333,stroke-width:2px
        style M fill:#f99,stroke:#333,stroke-width:2px
        style N fill:#9f9,stroke:#333,stroke-width:2px
        style O fill:#f99,stroke:#333,stroke-width:2px
        style P fill:#f9f,stroke:#333,stroke-width:2px

## Nix Shell Tips

- Use the command flag to pass arguments to the mermaid CLI:
    nix shell nixpkgs#mermaid-cli --command bash -c 'mmdc -i input.mmd -o output.png -e png'

- The command flag is required because mermaid-cli is a Node.js package and needs to be invoked through bash.

- For large diagrams, consider using jobs to parallelize rendering:
    nix shell nixpkgs#mermaid-cli --command bash -c 'mmdc -i input.mmd -o output.png -e png --jobs 8'

## References

- Mermaid Documentation: https://mermaid.js.org/
- Mermaid CLI: https://mermaid.ai/open-source/config/mermaidCLI.html
- NixOS Mermaid Tutorial: https://kb.shells.com/tutorials/nixOS_Latest/Mermaid/
