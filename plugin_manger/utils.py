import ast
import importlib
import sys
import traceback
from pathlib import Path
from typing import Optional, List, Any, Dict

from nonebot.matcher import matchers
from nonebot.plugin import load_plugin, _plugins, _managers

from zhenxun.builtin_plugins.admin.plugin_switch._data_source import plugin_row_style
from zhenxun.models.plugin_info import PluginInfo
from zhenxun.utils._image_template import ImageTemplate
from zhenxun.utils.message import MessageUtils


class PluginManger:
    plugin_roots: List[Path] = [
        Path("zhenxun/plugins").resolve(),
        Path("zhenxun/builtin_plugins").resolve()
    ]
    unload_plugin_list: List[Dict[str, Optional[str]]] = []
    _next_id: int = 1

    @classmethod
    async def plugin_list(cls):
        plugin_lists = await PluginInfo.get_plugins()

        column_name = [
            "ID",
            "模块",
            "名称",
            "全局状态",
            "禁用类型",
            "加载状态",
            "作者",
            "版本",
        ]

        column_data = [
            [
                plugin.id,
                plugin.module,
                plugin.name,
                "开启" if plugin.status else "关闭",
                plugin.block_type,
                "SUCCESS" if plugin.load_status else "ERROR",
                plugin.author,
                plugin.version,
            ]
            for plugin in plugin_lists
        ]

        pic = await ImageTemplate.table_page(
            "Plugin",
            "插件状态",
            column_name,
            column_data,
            text_style=plugin_row_style,
        )
        return pic

    @classmethod
    async def plugin_load(cls, plugin_path: str) -> str:
        if plugin_path is None:
            return "ERROR"

        # 检查插件是否已经在 _plugins 中
        for plugin in _plugins.values():
            if getattr(plugin, "module_name", None) == plugin_path:
                return "EXIST"

        try:


            load_plugin(plugin_path)
            await cls.get_noload_plugins()

            return "SUCCESS"
        except Exception:
            return "LOAD_ERROR"

    @classmethod
    async def plugin_unload(cls, plugin: PluginInfo) -> str:
        """
        卸载插件，返回状态码：
            "NOT_FOUND"   - 插件在 _plugins 中不存在
            "NOT_MANAGED" - 插件不在任何管理器中
            "SUCCESS"     - 卸载成功
            "ERROR"       - 卸载时异常
        """

        plugin_name = plugin.module
        if plugin_name not in _plugins:
            return "NOT_FOUND"

        if not any(plugin_name in m.available_plugins for m in _managers):
            return "NOT_MANAGED"

        try:
            module_name = _plugins[plugin_name].module_name

            # 清除 matchers
            for priority, mset in list(matchers.items()):
                for m in list(mset):
                    if getattr(m, "plugin_name", None) == plugin_name:
                        m.destroy()
                if not matchers[priority]:
                    del matchers[priority]

            # 删除 sys.modules 中插件模块及其子模块
            to_delete = [mod for mod in list(sys.modules) if module_name in mod]
            for mod in to_delete:
                del sys.modules[mod]

            # 删除插件记录
            del _plugins[plugin_name]
            _managers[:] = [m for m in _managers if plugin_name not in m.available_plugins]

            # 清理缓存
            importlib.invalidate_caches()
            await plugin.delete()
            await cls.get_noload_plugins()
            return "SUCCESS"
        except Exception:
            return "ERROR"


    @classmethod
    async def plugin_noload_list(cls):
        _plugin_list = await cls.get_noload_plugins()

        if not _plugin_list:
            await MessageUtils.build_message("没有未加载的插件").finish(reply_to=True)
            return

        column_name = ["ID","模块", "名称", "描述"]
        column_data = [
            [p["id"],p["module"], p["name"], p["description"]] for p in _plugin_list
        ]

        pic = await ImageTemplate.table_page(
            "Plugin",
            "插件状态",
            column_name,
            column_data,
            text_style=plugin_row_style,
        )
        return pic

    @classmethod
    async def get_noload_plugins(cls) -> List[Dict[str, Optional[str]]]:
        results: List[Dict[str, Optional[str]]] = []

        loaded_modules = {name for name in sys.modules if name.startswith("zhenxun.plugins.") or name.startswith("zhenxun.builtin_plugins.")}

        for root in cls.plugin_roots:
            if not root.exists():
                continue

            for item in root.iterdir():
                if item.name.startswith("_"):
                    continue

                if item.is_file() and item.suffix == ".py":
                    plugin_file = item
                    module_name = item.stem
                elif item.is_dir() and (item / "__init__.py").exists():
                    plugin_file = item / "__init__.py"
                    module_name = item.name
                else:
                    continue

                # 根据不同根目录生成模块路径
                if root.name == "plugins":
                    module_path = f"zhenxun.plugins.{module_name}"
                else:  # builtin_plugins
                    module_path = f"zhenxun.builtin_plugins.{module_name}"

                if module_path in loaded_modules:
                    continue

                meta_name = meta_description = None
                try:
                    source = plugin_file.read_text(encoding="utf-8")
                    meta = cls.parse_plugin_metadata(source)
                    meta_name = meta.get("name")
                    meta_description = meta.get("description")
                except Exception:
                    pass

                plugin_id = cls._next_id
                cls._next_id += 1

                results.append({
                    "id": plugin_id,
                    "module": module_name,
                    "name": meta_name,
                    "module_path": module_path,
                    "description": meta_description,
                })

        # 更新 unload_plugin_list
        cls.unload_plugin_list = results
        return results

    @staticmethod
    def parse_plugin_metadata(source: str) -> dict:
        def ast_literal(node: ast.AST) -> Any:
            try:
                return ast.literal_eval(node)
            except Exception:
                return None

        tree = ast.parse(source)

        for node in tree.body:
            if isinstance(node, ast.Assign):
                if not any(
                    isinstance(t, ast.Name) and t.id == "__plugin_meta__"
                    for t in node.targets
                ):
                    continue

                value = node.value

                if (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id == "PluginMetadata"
                ):
                    result = {}
                    for kw in value.keywords:
                        key = kw.arg
                        literal = ast_literal(kw.value)
                        if literal is not None:
                            result[key] = literal
                        else:
                            result[key] = ast.unparse(kw.value)
                    return result
        return {}

    @classmethod
    async def find_noload_plugin(cls, _value, _type):
        await cls.get_noload_plugins()
        print(cls.unload_plugin_list)
        for plugin in cls.unload_plugin_list:
            if _type == "name" and plugin.get("module") == _value:
                return plugin.get("module_path")
            elif _type == "id" and str(plugin.get("id")) == str(_value):
                return plugin.get("module_path")
            elif _type == "path" and plugin.get("module_path") == _value:
                return plugin.get("module_path")
        return None
