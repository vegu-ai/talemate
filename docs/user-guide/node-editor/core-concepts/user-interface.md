# Using the node editor

--8<-- "docs/snippets/common.md:documentation-is-a-work-in-progress"

The node editor is available in the main scene window once the scene is switched to creative mode.

Switch to creative mode through the creative mode toggle in the scene toolbar.

![Switch to creative mode](../img/toggle-node-editor.png)

## Module Library

![Module Library](../img/user-interface-0001.png)

The **:material-group: Modules** Library can be found at the bottom of the editor.

It holds all the node modules that talemate has currently installed and is the main way to add new modules to the editor or open existing modules for inspection or editing.

### Module listing

Node modules come in three categories:

- Scene level modules: Purple, these modules live with scene project
- Installed modules: Brown, these are the modules installed through the `templates/modules` directory
- Core modules: Grey, these are the modules that are part of the core talemate installation

All modules can be opened and inspected, but **only scene level modules can be edited**.

Installed and core modules will have a **:material-lock: Lock** icon next to their name. This means that they cannot be edited, but they can still be opened and inspected and copied into an editable scene level module.

![Module Library Lock Icon](../img/user-interface-0003.png)

!!! note "Modularity and load order explained"
    Read the [Modularity](modularity.md#module-load-order) section for more information on the load order of the modules.

### Filtering modules

Type search terms into the **Filter** field to only show modules that match the search terms.

![Module Library Filtering](../img/user-interface-0002.png)

### Opening modules

To open a module, click on the module you want to open.

Onced opened the module will be loaded into to node editor.

### Creating modules

To create a new scene module, click the **:material-plus: Create Module** button.

![Module Library Create Module](../img/user-interface-0004.png)

Select the appropriate module type.

| Module Type | Description |
|-------------|-------------|
| :material-file-multiple: Copy current | Copies the currently open module into a new module |
| :material-source-fork: Extend current | [Extends](module-inheritance.md) the currently open module into a new module |
| :material-console-line: Command | Creates a new [command](command-module.md) module |
| :material-alpha-e-circle: Event | Creates a new [event](events.md) module |
| :material-function: Function | Creates a new [function](functions.md) module |
| :material-file: Module | Creates a new module |
| :material-source-branch-sync: Scene Loop | Creates a new scene loop module |

In the upcoming dialog you can name the new module and set the registry path.

![Module Library Create Module Dialog](../img/user-interface-0005.png)

The registry path is the path to the module in the module library. 

The registry path must have at least two parts, the first part is the path to the module in the module library, the second part is the name of the module.

!!! note "Use $N in the registry path"
    The registry path can contain a `$N` placeholder. This will be replaced with a name generated from the module title.

    For example, if the module title is "My Module", the registry path will be `path/to/my/modules/$N`.

    The `$N` placeholder will be replaced with a name generated from the module title.

### Deleting modules

To delete a scene module click the :material-close-circle-outline: icon next to the module name.

!!! warning "Cannot be undone"
    Deleting a module is irreversible and cannot be undone.

## Node Editor

The node editor is made up of the toolbar, the canvas and the log watcher.

### Canvas

The canvas is the main area where you can add, connect and edit nodes.

![Node Editor](../img/user-interface-0007.png)

### Log Watcher

Certain nodes can log messages to the log watcher. It is located in the upper right corner of the editor.

![Node Editor Log Watcher](../img/user-interface-0008.png)

### Toolbar 

![Node Editor Toolbar](../img/user-interface-0010.png)

The toolbar shows the path of the currently open module and provides:

- A debug menu
- Testing controls
- Save

#### :material-bug: Debug Menu

Allows you to toggle on or off some debug options.

![Node Editor Debug Menu](../img/user-interface-0009.png)

| Debug Option | Description |
|-------------|-------------|
| Set State | Causes Set State nodes to log their state to the log watcher |
| Get State | Causes Get State nodes to log their state to the log watcher |
| Clear Log on Test | Clears the log watcher on test |

#### :material-movie-play: Start Scene Test

Clicking the :material-movie-play: button will start the scene loop for testing.

This is useful if you want to stay in the module that you are currently editing, but want to start a testing run of the scene.

!!! note "Saving the module before testing"
    In order for the scene loop to pick up the current changes in the open module, you need to save the module first.

#### :material-play: Start Module Test

Clicking the :material-play: button will start a disconnected test run of the currently open module.

#### :material-stop: Stop Test

Clicking the :material-stop: button will stop the current test run.

#### Breakpoint controls

When a `Breakpoint` node is processed the module execution will pause and the toolbar will show the breakpoint controls.

![Node Editor Breakpoint Controls](../img/user-interface-0011.png)

| Breakpoint Control | Description |
|-------------|-------------|
| :material-debug-step-over: | Will open the module that triggered the breakpoint |
| :material-play-pause:| Releases the breakpoint and continues the module execution |

### Nodes

#### Adding a node

To add a node to the module, right click the canvas and select **Add Node**, then browse through the context menu to find the node you want to add.

![Node Editor Add Node](../img/user-interface-0006.png)

#### Node Search

Alternatively, double clicking the canvas will open the node search.

Type in the search field to filter the nodes.

![Node Editor Node Search](../img/user-interface-0012.png)

Click on the node you want to add to the canvas.

!!! tip "Press enter to add the top result"
    Pressing enter will add the top result to the canvas.

#### Connecting nodes

To connect nodes, click and drag from the output slot (right) of one node to the input slot (left) of another node.

![Node Editor Connect Nodes](../img/user-interface-0013.png)

![Node Editor Connect Nodes](../img/user-interface-0014.png)

#### Disconnecting nodes

Drag the output slot of one node to the canvas to disconnect it.

#### Selecting nodes

To select a single node, click on it, it will have a white border to indicate that it is selected.

![Node Editor Select Node](../img/user-interface-0015.png)

To select *multiple* nodes, hold the `Ctrl` key and drag a rectangle around the nodes you want to select.

![Node Editor Select Multiple Nodes](../img/user-interface-0016.png)

To add to a selection, hold the `Shift` key and click on the node.

To add multiple nodes to a selection, hold the `Ctrl+Shift` key and drag a rectangle around the nodes you want to add to the selection.

#### Deleting nodes

Select the node(s) and hit the `DEL` key to delete it.

#### Moving nodes

To move a single node simply hold the mouse button down and drag the node to the desired location.

To move multiple selected nodes hold the `Shift` key and drag the nodes to the desired location.

#### Resizing a node

To resize a node, move the mouse around the bottom right corner of the node until the resize cursor appears.

Then hold and drag the bottom right corner to resize the node.

#### Copying nodes

##### Ctrl+C / Ctrl+V

To copy a node, select it and hit `Ctrl+C`.

To paste a node, select the location where you want to paste it and hit `Ctrl+V`.

##### Alt drag to duplicate

You can also hold the `Alt` key and drag the selected node(s) to duplicate them and drag the duplicate to the desired location.

#### Node Properties

Most nodes come with properties that can be edited. To edit a node property, click on the corresponding input widget in the node.

A window will open with an appropriate input method to update the property.

#### Node title

You can change the title of any node by right clicking on it and then selecting `Title`.

##### Auto titling

Some nodes support auto titling. To auto title a node, hold `Shift` and click the node's title. 

The `Get State` node for example will auto title to display the `<scope>` and the `<variable name>`.

![Node Editor Auto Titling](../img/user-interface-0017.png)

### Groups

![Node Editor Groups](../img/user-interface-0018.png)

Groups allow you to group nodes together by color schemes.

Any nodes inside a group will move with the group when the group is moved.

#### Adding a group

Right click on the canvas and select `Add Group`.

#### Group Properties

Edit a group's properties by right clicking the group and the n`Edit Group` option.

##### Title

Set the title of the group.

##### Color

Set the color of the group.

#### Deleting a group

Right click on the group and select `Edit Group` -> `Remove Group`.

#### Moving a group

Click and hold the group title to move the group.

#### Resizing a group

Move the mouse around the bottom right corner of the group until the resize cursor appears.

Then hold and drag the bottom right corner to resize the group.

#### Group control shortcuts

There are some convenience shortcuts for groups, they are activated by **clicking the group title while holding a modifier key**.

| Modifier Key| Description |
|-------------|-------------|
| `Ctrl` | Resize the group to neatly frame the nodes inside it |
| `Shift` | Create a new group beneath with the same width, color and title |
| `Alt` | Snap the group the group above it, aligning its top-left corner with the bottom-right corner of the other group |

### Comments

To add a comment right click the canvas and select `Comment`.

Double click the comment to edit the text.

![Node Editor Comment](../img/user-interface-0019.png)