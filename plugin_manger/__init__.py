
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot_plugin_alconna import Alconna, Args, on_alconna, Option, UniMessage, Subcommand, CommandResult

from zhenxun.configs.utils import PluginExtraData, RegisterConfig
from zhenxun.models.plugin_info import PluginInfo
from zhenxun.utils.enum import PluginType
from zhenxun.utils.message import MessageUtils
from .utils import PluginManger, get_target_plugin

__plugin_meta__ = PluginMetadata(
    name="插件管理",
    description="对插件进行管理",
    usage="""
    插件管理，可以对插件进行加载、卸载、重载
    用法：
        插件管理 列表
        插件管理 未加载插件
        插件管理 加载 [plugin模块名称] [-D 插件ID] [-P 模块路径]
        插件管理 卸载 [plugin模块名称] [-D 插件ID] [-P 模块路径]
        插件管理 重载 [plugin模块名称] [-D 插件ID] [-P 模块路径]
    
      示例：
        插件管理 加载|卸载|重载 music
        插件管理 加载|卸载|重载 -D 22
        插件管理 加载|卸载|重载 -P zhenxun.plugins.music
    
    tip:
        仅支持zhenxun文件夹下的插件目录
    """.strip(),

    extra=PluginExtraData(
        author="Uesugi Hanako",
        version="0.1",
        configs=[
            RegisterConfig(
                module="plugin_manger",
                key="developer-mode",
                value=False,
                help="开发者模式(开启允许操作builtin_plugins)",
                type=bool,
                default_value=False,
            ),
            ],
        plugin_type=PluginType("SUPERUSER"),
    ).to_dict(),
)



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


    result = await PluginManger.plugin_load(plugin_path)
    if result=="SUCCESS":
        await UniMessage(f"插件 {plugin_path} 加载成功").send(reply_to=True)
    elif result=="EXIST":
        await UniMessage(f"插件 {plugin_path} 已存在").send(reply_to=True)
    elif result=="LOAD_ERROR":
        await UniMessage(f"插件 {plugin_path} 加载时发生错误").send(reply_to=True)
    else:
        await UniMessage(f"未找到插件 {plugin_path}").send(reply_to=True)

@plugin_manager.assign("卸载")
async def plugin_unload_handle(args: CommandResult):
    arg = args.result.all_matched_args
    target_value, target_type = get_target_plugin(arg)

    # 查询方式映射
    query_map = {
        "name": ("module", str(target_value)),
        "id": ("id", str(target_value)),
        "path": ("module_path", str(target_value))
    }

    if target_type not in query_map:
        await UniMessage("请输入有效的插件信息（名称、ID或路径）").send(reply_to=True)
        return

    field, value = query_map[target_type]

    # 获取插件信息
    plugin = await PluginInfo.get_plugin(**{field: value})
    if not plugin:
        await UniMessage("未找到指定插件").send(reply_to=True)
        return

    # 卸载插件
    result = await PluginManger.plugin_unload(plugin)
    if result == "SUCCESS":
        await UniMessage(f"插件 {plugin.name} 已成功卸载").send(reply_to=True)
    elif result == "ERROR":
        await UniMessage(f"插件 {plugin.name} 卸载时发生错误").send(reply_to=True)
    else:
        await UniMessage(f"插件 {plugin.name} 未找到").send(reply_to=True)



@plugin_manager.assign("重载")
async def plugin_reload_handle(args:CommandResult):
    arg = args.result.all_matched_args
    target_value, target_type = get_target_plugin(arg)

    # 查询方式映射
    query_map = {
        "name": ("module", str(target_value)),
        "id": ("id", str(target_value)),
        "path": ("module_path", str(target_value))
    }

    if target_type not in query_map:
        await UniMessage("请输入有效的插件信息（名称、ID或路径）").send(reply_to=True)
        return

    field, value = query_map[target_type]

    # 获取插件信息
    plugin = await PluginInfo.get_plugin(**{field: value})
    if not plugin:
        await UniMessage("未找到指定插件").send(reply_to=True)
        return

    result = await PluginManger.plugin_reload(plugin)
    if result == "SUCCESS":
        await UniMessage(f"插件 {plugin.name} 已成功重载").send(reply_to=True)
    elif result == "ERROR":
        await UniMessage(f"插件 {plugin.name} 重载时发生错误").send(reply_to=True)
    elif result == "LOAD_ERROR":
        await UniMessage(f"插件 {plugin.name} 加载时发生错误").send(reply_to=True)
    elif result == "UNLOAD_ERROR":
        await UniMessage(f"插件 {plugin.name} 卸载时发生错误").send(reply_to=True)
    else:
        await UniMessage(f"插件 {plugin.name} 未找到").send(reply_to=True)

