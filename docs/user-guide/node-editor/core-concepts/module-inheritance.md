# Module Inheritance

Module inheritance allows node modules to extend other node modules, creating a system for building upon existing functionality while maintaining references to the base module's components.

!!! tip "Learn about modularity"
    Learn more about [node modules](modularity.md).

## What is Module Inheritance?

Module inheritance is a feature that enables a node module to **extend** another module, inheriting all of its nodes, connections, and structure. This is not about Python class inheritance - it's about visual composition and extension of node graphs.

When a module extends another:

- All nodes from the base module appear in the extending module
- These inherited nodes maintain a reference to the base module
- Changes to the base module automatically propagate to all modules that extend it
- The extending module can add new node logic, but cannot modify the base module's logic

## Creating Module Extensions

### From the Module Library

To extend an existing module:

1. Open the module you want to extend in the node editor
2. Click the **Create module** button
3. Select **Extend current** from the menu
4. Provide a name and registry path for your extension
5. The new module will inherit all nodes from the base module

## How It Works

Module inheritance is established by setting the `extends` property when creating or configuring a module. The system will:

1. Load all nodes, edges, groups, and comments from the base module
2. Mark inherited components with an `inherited` flag
3. Allow the extending module to add new components
4. Maintain the connection between base and extending modules

### Live References

The key feature of module inheritance is **references**. When you extend a module:

- You're not copying the base module's nodes
- You're referencing them directly
- Updates to the base module automatically apply to all extending modules
- This ensures consistency and reduces maintenance

## Copy vs Extend

When working with existing modules, you have two options:

### Copy
- Creates an independent duplicate
- No connection to the original module
- Changes to the original don't affect the copy
- Use when you need complete independence

### Extend
- Maintains inheritance relationship
- Receives updates from the base module
- Can only add to, not remove from or change the base
- Use when you want to build upon existing functionality