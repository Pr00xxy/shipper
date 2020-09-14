# Shipper

This project is based on the concept of atomic deployments with focus on modularity.

Shipper does nothing except creating and maintaining the atomic deployment structure.

Any implementation or custom integrations are done by the user with the use of hooks.

This project is a pet project. Distributed publicly in the hopes that someone finds it useful. 


## Execution flow
Shipper will out of the box execute the following tasks

1. Attempt to ssh to the target machine
2. Create a directory for keeping deployments (By me called "revisions")
3. Create a specific directory in the revisions directory that is unique to this execution.
4. Create symlinks to assets that should persist over revisions
5. Create a symlink at a desired location that points to the new revision  
*This symlink is where I point the webserver*

6. Rotate old revisions that have expired

## Requirements

- ssh
- python3

### Configuration

- `--config` path to configuration file. See `shipper.json` for sample version

Configuration provided in the config file can be overridden by passing env vars.

Shipper will read all environment variables prefixed with `SHIP_`

More information about the configuration library used can be found [here](https://github.com/tr11/python-configuration#configuration)

### Configuration in depth

#### "events": {},
Where event config is loaded from. More details in a later

#### config.revision
Name of the new revision

#### config.revisions_to_keep
How many revisions to keep as a backup.
Default is 5

#### fail_on_symlink_error
If shipper should throw ShipperError when optional symlink creation fails

#### active_symlink
path to the symlink which points to the "current" revision

#### config.directories.revisions
Path to directory where revisions are kept

#### config.symlinks
List of symlinks to be created
Symlinks sources are absolute to the filesystem whereas the target symlink is relative to the revision directory

```json
"symlinks": {
  "/path/to/file": "path/to/link"
} 
```

NOTE! Files and directories that exist at the link path will be removed.

## Extensions

By default shipper is a very dumb script.

Extending shipper is done by adding listeners to hooks executed by shipper.

Hooks are trigged by shipper and by looking in the source code we can see the event trigger:

```python
event.dispatch('before:init_directories')
```

To hook onto this event one must add a element to the event object in the config file.
Hooks are executed in the order they are defined.

```json
"events": {
    "before:init_directories": [
        "<module_name>.<class_name>.<func_name>"
    ]
}
```

The extension module can then be declared like so

```python
class MyCustomExtension(object):
    def __init__(self, shipper):
        self.shipper = shipper
        
    def my_func(self)
        print("hello world")
```

NOTE: Shipper will inject it's own instance as an argument, thus extensions must accept.