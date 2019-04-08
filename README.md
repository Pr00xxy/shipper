# Shipper 2.0

This project is grounded in the concept of atomic deployments with emphasising scalability and modularity
 
Shipper was built to be run on Linux.

## Requirements

- python3

## Usage

```
python3 <(curl -sS https://raw.githubusercontent.com/Pr00xxy/shipper/master/shipper.py)
```


### Options

- `--revision` string of whatever you want the revision directory name to be
- `--deploy-dir` path to where Shipper should work. (default: where it's executed)
- `--deploy-cache-dir` location of you soon to be latest release (default: `cache` within `deploy-dir`)
- `--revisions-to-keep` number of old revisions to keep in addition to the current revision (default: `5`)
- `--symlinks`
    This can either be a JSON hash of symlinks or
    the filepath to a file containing json data
- `--help` prints help and usage instructions
- `--plugin-file` path to plugin file
- `--plugin-json` json hash that will be passed to the plugin

#### Plugins

Plugins are user made modules that can be hooked into the code at will.

To define a new plugin one must create a json file and pass it to shipper with
--plugin
Plugins are executed by dispatching events in the shipper code.  
Looking inside the `Deployer.run()` we can find plugin dispatchers such as:

    self.dispatchEvent('before:initDirectories', pluginPath)

To add plugin to this event one must add the following structure to `plugin.json`:

    {
        "action": {
            "before:initDirectories": {
                "execute": [
                    {
                        "name": "plugin.module_name.class_name.function_name"
                    }
                ]
            }
        }
    }

the `execute` directive tells Shipper what to execute and in what order.
In the example above Shipper will try to include `module_name` in the folder `plugin/` and from that import `class_name` and then execute `function_name`

above can be translated to

    from plugin.module_name import class_name

    function_name()

Multiple instructions can be added to the `execute` array
Functions are executed as if they were a part of the `Deployer` class

#### Symlinks

Symlinks are specified as `{"target":"linkname"}` and passed to the shipper script using the `--symlinks` parametert

- `target` is relative to the `--deploy-dir` path
- `linkname` is relative to the revision path

Symlinks can be specified as strings or as the path to json file containing the json array.

**NOTE!** Files and directories that exist at the link location will be removed without notice.