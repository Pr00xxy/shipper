# Shipper

This project is based on the concept of sharing resources across deployments in combination with the need of modularity and scaleability.
Shipper was built to be run on Linux

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

Plugins are user made modules that can injected in the code at will.

To define a new plugin one must create a json file and pass it to shipper with
--plugin
Looking inside the `Deployer.run()` we can find plugin dispatchers such as:

    self.dispatchEvent('before:initDirectories', pluginPath)

To add plugin to this event one must add the following structure to `plugin.json`:

    {
        "action": {
            "before:initDirectories": {
                "execute": [
                    {
                        "name": "plugin.module_name.class_name.function_name",
                        "data": [
                            { "foo": "bar" },
                            { "biz": "baz" },
                            { "int": 1 }
                        ]
                    }
                ]
            }
        }
    }

the `execute` directive tells Shipper what to execute and in what order.
In the example above Shipper will try to include `module_name` in the folder `plugin/` and from that import `class_name` and then execute `function_name`
The `data` array will pass the content the array as is to the function being called. All flag values are also passed into the plugin

above can be translated to

    from plugin.module_name import class_name

    function_name()

Multiple instructions can be added to the `execute` array

#### Symlinks

Symlinks are specified as `{"target":"linkname"}`

- `target` is relative to the `--deploy-dir` path
- `linkname` is relative to the revision path

symlinks can be specified as strings or as filepaths.

**NOTE!** Files and directories that exist at the link location will be removed without notice.