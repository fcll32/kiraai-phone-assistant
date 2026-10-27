# 旧版手动服务器设置（进阶用法）

1.2.0 已内置手机连接服务，安装插件 ZIP 后即可在 KiraAI 页面准备连接，无需执行本文件中的命令。下面仅供继续使用旧版 Nginx 方案的用户参考；使用时关闭插件的“内置手机连接服务”。

第一次使用建议从 [新手使用说明](../新手使用说明.md) 开始。本文件补充服务器的操作步骤和不同安装情况。

设置完成后，手机只需要填 `你的公网IP:8443`，不用手写后面的连接路径。手机不需要开放端口。

## 普通 Ubuntu / Debian 服务器

先把源码包上传、解压，进入 `give-ai-a-phone` 文件夹，在服务器终端执行下面的命令。

安装工具：

```sh
sudo apt-get update
sudo apt-get install -y python3 openssl nginx
```

生成连接信息，把示例 IP 换成自己的：

```sh
python3 deploy/setup_public_ip.py --ip 203.0.113.10
cat deploy/generated/app-config.txt
```

文件里有“服务器地址”“连接密码”“服务器校验码”三项，按名字复制到手机 App。连接密码还要复制到 KiraAI 插件的“自定义连接密码（可选）”。

然后启用连接设置：

```sh
sudo cp deploy/generated/nginx-phone.conf /etc/nginx/conf.d/kira-phone.conf
sudo nginx -t
```

看到 `syntax is ok` 和 `test is successful` 才执行：

```sh
sudo systemctl reload nginx
```

最后，在云服务器平台的安全组中允许进入的 TCP 8443 端口。如果系统防火墙已开启，也要允许这个端口。

生成程序只负责写文件，不会自动修改防火墙或启用服务，所以后面的步骤也需要完成。

## 我的 KiraAI 端口不是 5267

默认按 KiraAI 在服务器的 5267 端口运行来生成设置。

假如你实际改成了 9000，首次生成时用下面的命令，其他步骤相同：

```sh
python3 deploy/setup_public_ip.py --ip 203.0.113.10 --upstream http://127.0.0.1:9000
```

这里的 9000 是 KiraAI 自己的端口。手机仍填 `你的公网IP:8443`。

## 8443 已经被其他程序使用

可以换成另一个未使用的端口，比如 8444。下面使用新的输出文件夹，不覆盖已经生成的设置：

```sh
python3 deploy/setup_public_ip.py --ip 203.0.113.10 --port 8444 --output deploy/generated-8444
cat deploy/generated-8444/app-config.txt
sudo cp deploy/generated-8444/nginx-phone.conf /etc/nginx/conf.d/kira-phone.conf
sudo nginx -t
```

检查通过后，再执行 `sudo systemctl reload nginx`。安全组需要允许 TCP 8444，手机也改填 `你的公网IP:8444`，并复制新生成的密码和校验码。插件的“自定义连接密码（可选）”也要同步改为新密码，保存后重新加载插件。

## KiraAI 装在 Docker 容器里

需要先让服务器能访问容器里的 KiraAI。例如把容器的 5267 端口映射到服务器的 `127.0.0.1:5267`，然后按普通步骤生成设置。

如果你使用服务器面板管理容器，在它的端口映射设置中查看实际端口。如果 KiraAI 映射到了其他端口，按上一节修改 `--upstream`。

## 为什么会有服务器校验码？

只有公网 IP、没有域名时，准备程序会生成服务器的识别信息。手机拿着校验码检查连到的是不是同一台服务器，复制即可，不需要自己计算。

本方案生成的证书有效期为 365 天。如果更换公网 IP、证书到期或需要更换设置，使用新的输出文件夹重新生成，再同时更新服务器、插件的连接密码和手机三项设置。原设置正常时，不需要重复生成。

如果服务器已经使用可信机构签发的证书，可以继续使用它，手机的校验码留空；连接转发的技术细节见 [开发与构建](../DEVELOPMENT.md)。

## 生成文件放在哪里？

默认在 `deploy/generated/`。`app-config.txt` 是给人看的连接信息，其他文件供服务器使用。启用后不要直接移动这个文件夹，因为服务器设置记住了它的位置。

如果报错，先保留完整错误文字。常见情况的排查顺序已经写在新手说明最后一节。
