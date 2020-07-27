**use Python 3.x in order to execute**

## Development
Crate a virtal environment and source said venv
``` bash
$ virtualenv venv
$ source venv/bin/activate
$ pip install -r requirements.txt
$ python run_bm.py
```

*If your distro doesn't use python3.x as python (e.g. ubuntu) you need to install python 3 the following way*
``` bash
$ sudo apt install python3
$ virtualenv -p /usr/bin/python3.*X* venv #replace X
$ source venv/bin/activate
$ python -V #should display 3.x.x
```
