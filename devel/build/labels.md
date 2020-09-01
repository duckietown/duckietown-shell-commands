# Docker Image Labels

All Docker images in Duckietown will store important metadata using image labels.
All the labels supported by Duckietown will have the prefix `org.duckietown.label`.


## Image labels

- `org.duckietown.label.image.authoritative`: Whether the image contains official Duckietown code;
  - Type: `boolean`
  - Default: `False`

- `org.duckietown.label.image.loop`: Whether the image is a LOOP image. Experimental only and for development only.
  - Type: `boolean`
  - Default: `False`
  
- `org.duckietown.label.image.configuration.X`: Image configuration `X` encoded as a JSON string;
  - Type: `json`
  - Default: `undefined`


## Module labels

- `org.duckietown.label.module.type`: Module contained in the image;
  - Type: `string`
  - Default: `undefined`

- `org.duckietown.label.module.description`: Description of the module contained in the image;
  - Type: `string`
  - Default: `undefined`

- `org.duckietown.label.module.icon`: Name of an icon for this module, pick one from https://fontawesome.com/v4.7.0/icons;
  - Type: `string`
  - Default: `box`


## Build labels

- `org.duckietown.label.time`: Build time (UTC in ISO format)
  - Type: `string`
  - Default: `ND`


## System labels

- `org.duckietown.label.architecture`: Target architecture;
  - Type: `string`
  - Default: `undefined`


## Code labels

- `org.duckietown.label.code.location`: Path (inside the image) to this module's code;
  - Type: `string`
  - Default: `undefined`

- `org.duckietown.label.code.distro`: Distribution this image belongs to (e.g., daffy)
  - Type: `string`
  - Default: `undefined`

- `org.duckietown.label.code.version.head`: Only set when the project is clean and the repository HEAD is tagged 
  - Type: `string`
  - Default: `ND`

- `org.duckietown.label.code.version.closest`: Closest version in the code's versioning history
  - Type: `string`
  - Default: `ND`

- `org.duckietown.label.code.vcs`: Version control system
  - Type: `string`
  - Default: `undefined`

- `org.duckietown.label.code.repository`: Repository name
  - Type: `string`
  - Default: `undefined`

- `org.duckietown.label.code.sha`: Hash of the commit from which the image was generated
  - Type: `string`
  - Default: `ND`

- `org.duckietown.label.code.branch`: Repository branch
  - Type: `string`
  - Default: `undefined`

- `org.duckietown.label.code.url`: Repository URL
  - Type: `string`
  - Default: `undefined`

- `org.duckietown.label.code.launchers`: Comma-separated list of launchers
  - Type: `string`
  - Default: `undefined`


## Template labels

- `org.duckietown.label.template.name`: Name of the template
  - Type: `string`
  - Default: `undefined`

- `org.duckietown.label.template.version`: Version of the template
  - Type: `string`
  - Default: `undefined`


## Base image labels

- `org.duckietown.label.base.distro`: Base Docker image's code distro version
  - Type: `string`
  - Default: `undefined`

- `org.duckietown.label.base.image`: Base Docker image's image name
  - Type: `string`
  - Default: `undefined`

- `org.duckietown.label.base.tag`: Base Docker image's tag name
  - Type: `string`
  - Default: `undefined`
