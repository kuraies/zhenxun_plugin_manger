import ast
import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Any, Dict, Callable

from nonebot.matcher import matchers
from nonebot.plugin import load_plugin, _plugins, _managers, PluginMetadata

from zhenxun.builtin_plugins.admin.plugin_switch._data_source import plugin_row_style
from zhenxun.configs.config import Config
from zhenxun.configs.utils import PluginExtraData, PluginSetting
from zhenxun.models.plugin_info import PluginInfo
from zhenxun.utils._image_template import ImageTemplate
from zhenxun.utils.enum import (
    PluginType,
)
from zhenxun.utils.message import MessageUtils


@dataclass(frozen=True)
class PluginSource:
    name: str
    path: Path
    enabled: Callable[[], bool]

    @property
    def module_prefix(self) -> str:
        """
        根据插件源路径推导 Python 模块前缀
        前提：path 指向的是一个 Python package 目录
        """
        return ".".join(self.path.parts)



class PluginManger:

    PROJECT_ROOT = Path("zhenxun")

    unload_plugin_list: List[Dict[str, Optional[str]]] = []
    _next_id: int = 1

    PLUGIN_SOURCES: List[PluginSource] = [
        PluginSource(
            name="user",
            path=Path("zhenxun/plugins"),
            enabled= lambda:True,
        ),
        PluginSource(
            name="builtin",
            path=Path("zhenxun/builtin_plugins"),
            enabled=lambda: Config.get_config("plugin_manger", "developer-mode"),
        ),
    ]

    @classmethod
    async def plugin_list(cls):
        plugin_lists = await PluginInfo.get_plugins()

        # 获取所有启用的插件源的 module_prefix
        enabled_prefixes = []
        for source in cls.PLUGIN_SOURCES:
            try:
                if source.enabled():
                    enabled_prefixes.append(source.module_prefix)
            except Exception:
                # 如果 enabled() 调用失败，跳过该插件源
                continue
        print(enabled_prefixes)
        print("config:",Config.get_config("plugin_manger", "developer-mode"))
        # 筛选插件：只显示来自已启用插件源的插件
        filtered_plugins = []
        for plugin in plugin_lists:
            if hasattr(plugin, 'module_path') and plugin.module_path:
                plugin_path_str = str(plugin.module_path)
                # 检查插件路径是否在任一已启用的插件源路径下
                for source_path in enabled_prefixes:
                    if source_path in plugin_path_str:
                        filtered_plugins.append(plugin)
                        break

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
            for plugin in filtered_plugins  # 使用筛选后的插件列表
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


            plugin=load_plugin(plugin_path)

            metadata = plugin.metadata
            if not metadata:
                if not plugin.sub_plugins:
                    return
                """父插件"""
                metadata = PluginMetadata(name=plugin.name, description="", usage="")
            extra = metadata.extra
            extra_data = PluginExtraData(**extra)
            setting = extra_data.setting or PluginSetting()
            if metadata.type == "library":
                extra_data.plugin_type = PluginType.HIDDEN
            if extra_data.plugin_type == PluginType.HIDDEN:
                extra_data.menu_type = ""
            if plugin.sub_plugins:
                extra_data.plugin_type = PluginType.PARENT

            await PluginInfo(
                module=plugin.name,
                module_path=plugin.module_name,
                name=metadata.name,
                author=extra_data.author,
                version=extra_data.version,
                level=setting.level,
                default_status=setting.default_status,
                limit_superuser=setting.limit_superuser,
                menu_type=extra_data.menu_type,
                cost_gold=setting.cost_gold,
                plugin_type=extra_data.plugin_type,
                admin_level=extra_data.admin_level,
                is_show=extra_data.is_show,
                ignore_prompt=extra_data.ignore_prompt,
                parent=(plugin.parent_plugin.module_name if plugin.parent_plugin else None),
                impression=setting.impression,
            ).save()

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

            # 删除插件记录
            del _plugins[plugin_name]
            _managers[:] = [m for m in _managers if plugin_name not in m.available_plugins]


            # 删除 sys.modules 中插件模块及其子模块
            to_delete = [mod for mod in list(sys.modules) if module_name in mod]
            for mod in to_delete:
                del sys.modules[mod]

            await plugin.delete()

            # 清理缓存
            importlib.invalidate_caches()

            await cls.get_noload_plugins()
            return "SUCCESS"
        except Exception:
            return "ERROR"

    @classmethod
    async def plugin_reload(cls, plugin: PluginInfo)->str:

        plugin_name = plugin.module
        if plugin_name not in _plugins:
            return "NOT_FOUND"

        try:
            unload_result = await cls.plugin_unload(plugin)

            if unload_result != "SUCCESS":
                return "UNLOAD_ERROR"

            load_result = await cls.plugin_load(plugin.module_path)
            if load_result != "SUCCESS":
                return "LOAD_ERROR"

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
    def get_enabled_sources(cls) -> List[PluginSource]:
        return [s for s in cls.PLUGIN_SOURCES if s.enabled()]

    @classmethod
    def get_loaded_modules(cls) -> set[str]:
        prefixes = tuple(
            src.module_prefix + "."
            for src in cls.get_enabled_sources()
        )

        return {
            name
            for name in sys.modules
            if name.startswith(prefixes)
        }

    @classmethod
    async def get_noload_plugins(cls) -> List[Dict[str, Optional[str]]]:
        results: List[Dict[str, Optional[str]]] = []

        loaded_modules = cls.get_loaded_modules()

        for source in cls.get_enabled_sources():
            root = source.path
            if not root.exists():
                continue

            module_prefix = source.module_prefix

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

                module_path = f"{module_prefix}.{module_name}"

                if module_path in loaded_modules:
                    continue

                meta_name = meta_description = None
                try:
                    source_code = plugin_file.read_text(encoding="utf-8")
                    meta = cls.parse_plugin_metadata(source_code)
                    meta_name = meta.get("name")
                    meta_description = meta.get("description")
                except Exception:
                    pass

                plugin_id = cls._next_id
                cls._next_id += 1

                results.append(
                    {
                        "id": plugin_id,
                        "source": source.name,
                        "module": module_name,
                        "module_path": module_path,
                        "name": meta_name,
                        "description": meta_description,
                    }
                )

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



def get_target_plugin(all_args: dict) -> tuple[str | None, str]:
    plugin = all_args.get("plugin")
    plugin_id = all_args.get("id")
    plugin_path = all_args.get("path")

    if plugin:
        return plugin, "name"

    for key in all_args:
        if key == "id" and plugin_id:
            return str(plugin_id), "id"
        if key == "path" and plugin_path:
            return str(plugin_path), "path"

    return None, ""