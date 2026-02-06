
from zhenxun.models.plugin_info import PluginInfo
from .utils import PluginManger

from nonebot.plugin import PluginMetadata,  get_loaded_plugins
from nonebot.permission import SUPERUSER


from zhenxun.configs.utils import PluginExtraData
from zhenxun.utils.enum import PluginType

from nonebot_plugin_alconna import Alconna, Args, on_alconna, Option, UniMessage, Subcommand, Query, CommandResult, \
    Match

__plugin_meta__ = PluginMetadata(
    name="插件管理",
    description="对插件进行管理",
    usage="{插件用法}",

    extra=PluginExtraData(
        author="Uesugi Hanako",
        version="0.1",

        plugin_type=PluginType.SUPERUSER,
    ).to_dict(),
)

from zhenxun.utils.message import MessageUtils

# plugin_manager = on_alconna(
#     Alconna("插件管理",
#             Subcommand("列表"),
#             Subcommand("未加载插件"),
#             Subcommand("加载",Args["plugin"]),
#             Subcommand("卸载",Args["plugin_name",str]),
#             Subcommand("重载",Args["plugin_name",str]),
#             ),
#     permission=SUPERUSER,
#     priority=5,
#     block=True,
# )

plugin_manager = on_alconna(
    Alconna("插件管理",
        Subcommand("列表"),
        Subcommand("未加载插件"),
        Subcommand("加载",
            Args["plugin",str,None],
            Option("-D|--id", Args["id",int],  help_text="按插件ID加载"),
            Option("-P|--path",Args["path",str],  help_text="按模块路径加载"),
        ),
        Subcommand("卸载",
            Args["plugin",str,None],
            Option("-D|--id", Args["id",int],  help_text="按插件ID加载"),
            Option("-P|--path",Args["path",str],  help_text="按模块路径加载"),
        ),
        Subcommand("重载",
            Args["plugin",str,None],
            Option("-D|--id", Args["id",int],  help_text="按插件ID加载"),
            Option("-P|--path",Args["path",str],  help_text="按模块路径加载"),
        ),
    ),
    permission=SUPERUSER,
    priority=5,
    block=True,
)



@plugin_manager.assign("列表")
async def plugin_list_handle():
   img = await PluginManger.plugin_list()
   await MessageUtils.build_message(img).finish(reply_to=True)

@plugin_manager.assign("未加载插件")
async def plugin_noload_handle():
    img = await PluginManger.plugin_noload_list()
    await MessageUtils.build_message(img).finish(reply_to=True)


@plugin_manager.assign("加载")
async def plugin_load_handle(args:CommandResult):
    arg = args.result.all_matched_args
    _value, _type =get_target_plugin(arg)

    if _value is None and _type == "":
        await UniMessage(f"请输入插件信息").send(reply_to=True)
        return

    plugin_path = await PluginManger.find_noload_plugin(_value, _type)


    if plugin_path is None:
        await UniMessage(f"未找到插件或插件已加载").send(reply_to=True)
        return


    result = PluginManger.plugin_load(plugin_path)
    if result=="SUCCESS":
        await UniMessage(f"插件 {plugin_path} 加载成功").send(reply_to=True)
    elif result=="EXIST":
        await UniMessage(f"插件 {plugin_path} 已存在").send(reply_to=True)
    elif result=="LOAD_ERROR":
        await UniMessage(f"插件 {plugin_path} 加载时发生错误").send(reply_to=True)
    else:
        await UniMessage(f"未找到插件 {plugin_path}").send(reply_to=True)

@plugin_manager.assign("卸载")
async def plugin_unload_handle(args:CommandResult):
    arg = args.result.all_matched_args
    _value, _type =get_target_plugin(arg)


    query_methods = {
        "name": ("module", str(_value)),
        "id": ("id", str(_value)),
        "path": ("module_path", str(_value))
    }

    if _type not in query_methods:
        await UniMessage("请输入有效的插件信息（名称、ID或路径）").send(reply_to=True)
        return

    field, value = query_methods[_type]
    _plugin = await PluginInfo.get_plugin(**{field: value})

    if _plugin is None:
        await UniMessage(f"未找到指定的插件").send(reply_to=True)
        return

    result = await PluginManger.plugin_unload(_plugin.module)

    # 处理卸载结果
    response_messages = {
        "SUCCESS": f"插件 {_plugin.name} 已成功卸载",
        "ERROR": f"插件 {_plugin.name} 卸载时发生错误",
        "NOT_FOUND": f"未找到插件 {_plugin.name}",
    }

    message = response_messages.get(result, f"未找到插件 {_plugin.name}")
    await UniMessage(message).send(reply_to=True)


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

    # 都没值
    return None, ""