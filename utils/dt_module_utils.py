ARCH_MAP = {
    'arm32v7': ['arm', 'arm32v7', 'armv7l', 'armhf'],
    'amd64': ['x64', 'x86_64', 'amd64', 'Intel 64'],
    'arm64v8': ['arm64', 'arm64v8', 'armv8', 'aarch64']
}
CANONICAL_ARCH = {
    'arm': 'arm32v7',
    'arm32v7': 'arm32v7',
    'armv7l': 'arm32v7',
    'armhf': 'arm32v7',
    'x64': 'amd64',
    'x86_64': 'amd64',
    'amd64': 'amd64',
    'Intel 64': 'amd64',
    'arm64': 'arm64v8',
    'arm64v8': 'arm64v8',
    'armv8': 'arm64v8',
    'aarch64': 'arm64v8'
}
BUILD_COMPATIBILITY_MAP = {
    'arm32v7': ['arm32v7'],
    'arm64v8': ['arm32v7', 'arm64v8'],
    'amd64': ['amd64']
}
DOCKER_LABEL_DOMAIN = "org.duckietown.label"
CLOUD_BUILDERS = {
    'arm32v7': 'ec2-3-215-236-113.compute-1.amazonaws.com',
    'arm64v8': 'ec2-3-215-236-113.compute-1.amazonaws.com',
    'amd64': 'ec2-3-210-65-73.compute-1.amazonaws.com'
}