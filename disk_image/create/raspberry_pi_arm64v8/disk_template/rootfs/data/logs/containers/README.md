# How to log containers

Use this feature only to debug containers when your robot is not reachable via network.
If your robot boots up fine, use `docker logs ...` instead.

At boot, the robot looks for directories inside `/data/logs/containers/` and if
it finds a match between a directory's name a docker container's name, it starts
logging to the file `0.log` inside that directory.
