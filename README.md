# 4d-static-docs
Static local copy of developer.4d.com

## Create a static local copy of developer.4d.com

- create a new folder "server" (or any name)
- in a new shell, set current directory
- `git clone https://github.com/4d/docs.git`
- `git checkout gh-pages`
- `npx serve ./`
- open `http://localhost:3000/docs` in browser to confirm the site is running
- create a new folder "mirror" (or any name)
- in a new shell, set current directory
 ```sh
wget --mirror \
      --convert-links \
      --adjust-extension \
      --page-requisites \
      --no-parent \
      http://localhost:3000/docs/
```
