# Project Name

Making pass #2 at creating a replacement for SportTracks 3.0.

Instead of a QT app this time going to try some sort of webframework
dockerized something or other.  Got way too sidetracked on version 1.0
with how to make a GUI and never even got off the ground with actually
getting a training log going.

## Links

- [Repo](https://github.com/btmullin/supertl2)
- [Live](...)
- [Bugs](https://github.com/btmullin/supertl2/issues)

## Screenshots

## Usage

In PowerShell:
```
docker build -t supertl2 .
docker run --rm -d -p 5000:5000 -v c:\git\supertl2:/app --name supertl2 supertl2
```

From browser:
[http://localhost:5000/](http://localhost:5000/)

## Built With

## Author

**Ben Mullin**

- [Profile](https://github.com/btmullin)
- [Email](mailto:benjamin.t.mullin@gmail.com)