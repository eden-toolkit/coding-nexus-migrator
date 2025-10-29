#!/bin/bash
# 快速构建脚本

echo "=== 构建工具分发包 ==="

# 安装构建工具
pip install build

# 构建分发包
python -m build

echo ""
echo "✅ 构建完成！"
echo "分发包位置:"
echo "  - 源码包: dist/coding-nexus-migrator-1.0.0.tar.gz"
echo "  - Wheel包: dist/coding-nexus-migrator-1.0.0-py3-none-any.whl"
echo ""
echo "部署到Linux服务器："
echo "1. 上传 .whl 文件到服务器"
echo "2. 运行: pip install coding-nexus-migrator-1.0.0-py3-none-any.whl"
echo "3. 设置环境变量"
echo "4. 运行: cnm migrate --projects your_project"