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


## Build labels

- `org.duckietown.label.module.type`: Module contained in the image;
  - Type: `string`
  - Default: `undefined`


## System labels

- `org.duckietown.label.architecture`: Target architecture;
  - Type: `string`
  - Default: `undefined`


## Code labels

- `org.duckietown.label.code.location`: Path (inside the image) to this module's code;
  - Type: `string`
  - Default: `undefined`

- `org.duckietown.label.code.version.major`: Version of this image's code
  - Type: `string`
  - Default: `undefined`

- `org.duckietown.label.code.vcs`: Version control system
  - Type: `string`
  - Default: `undefined`

- `org.duckietown.label.code.repository`: Repository name
  - Type: `string`
  - Default: `undefined`

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

- `org.duckietown.label.base.major`: Base Docker image's code major version
  - Type: `string`
  - Default: `undefined`

- `org.duckietown.label.base.image`: Base Docker image's image name
  - Type: `string`
  - Default: `undefined`

- `org.duckietown.label.base.tag`: Base Docker image's tag name
  - Type: `string`
  - Default: `undefined`
