"""
打包指令:
pyinstaller -F -n RC-main --windowed --icon=res\\icon.ico --add-data "res\\icon.ico;."  main.py
程序名：RC-main.exe
运行用户：当前登录用户（通过计划任务启动）
"""

#导入各种必要的模块
import io
import paho.mqtt.client as mqtt
import os
import psutil
import pystray
from PIL import Image
import wmi
from win11toast import notify
import json
import logging
from logging.handlers import RotatingFileHandler
from tkinter import messagebox
import sys
import threading
import subprocess
import time
import ctypes
import socket
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
import pyautogui
from pyautogui import press as pyautogui_press

BANBEN = "V2.1.0"

# 禁用 PyAutoGUI 安全模式，确保即使鼠标在屏幕角落也能执行命令
pyautogui.FAILSAFE = False

# 创建一个命名的互斥体
mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "RC-main")
# 检查互斥体是否已经存在
if ctypes.windll.kernel32.GetLastError() == 183:
    messagebox.showerror("错误", "应用程序已在运行。")
    sys.exit()

"""
执行系统命令，并在超时后终止命令。

参数:
- cmd: 要执行的命令（字符串或列表）
- timeout: 命令执行的超时时间（秒，默认为30秒）

返回值:
- 命令终止的返回码
"""


def execute_command(cmd: str, timeout: int = 30) -> int:
    """
    English: Executes a system command with an optional timeout, terminating the command if it exceeds the timeout
    中文: 使用可选超时时间执行系统命令，如果超时则终止命令
    """
    process = subprocess.Popen(cmd, shell=True)
    process.poll()
    if timeout:
        remaining = timeout
        while process.poll() is None and remaining > 0:
            logging.info(f"命令正在运行: {cmd}")
            time.sleep(1)
            remaining -= 1
        if remaining == 0 and process.poll() is None:
            logging.warning(f"命令超时，正在终止: {cmd}")
            process.kill()
    return process.wait()


"""
MQTT订阅成功时的回调函数。

参数:
- client: MQTT客户端实例
- userdata: 用户数据
- mid: 消息ID
- reason_code_list: 订阅结果的状态码列表
- properties: 属性
"""


def on_subscribe(client, userdata, mid, reason_code_list, properties=None):
    """
    English: Callback when MQTT subscription completes
    中文: MQTT成功订阅后回调函数
    """
    for sub_result in reason_code_list:
        if isinstance(sub_result, int) and sub_result >= 128:
            logging.error(f"订阅失败:{reason_code_list}")
        else:
            logging.info(f"使用代码发送订阅申请成功：{mid}")


"""
MQTT取消订阅时的回调函数。

参数:
- client: MQTT客户端实例
- userdata: 用户数据
- mid: 消息ID
- reason_code_list: 取消订阅结果的状态码列表
- properties: 属性
"""


def on_unsubscribe(client, userdata: list, mid: int, reason_code_list: list, properties) -> None:
    """
    English: Callback when MQTT unsubscription completes
    中文: MQTT取消订阅后回调函数
    """
    if len(reason_code_list) == 0 or not reason_code_list[0].is_failure:
        logging.info("退订成功")
    else:
        logging.error(f"{broker} 回复失败: {reason_code_list[0]}")
    client.disconnect()


"""
设置屏幕亮度。

参数:
- value: 亮度值（0-100）
"""


def set_brightness(value: int) -> None:
    """
    English: Sets the screen brightness to the specified value (0-100)
    中文: 设置屏幕亮度，取值范围为 0-100
    """
    try:
        logging.info(f"设置亮度: {value}")
        wmi.WMI(namespace="wmi").WmiMonitorBrightnessMethods()[0].WmiSetBrightness(
            value, 0
        )
    except Exception as e:
        logging.error(f"无法设置亮度: {e}")


"""
设置音量。

参数:
- value: 音量值（0-100）
"""


def set_volume(value: int) -> None:
    """
    English: Sets the system volume to the specified value (0-100)
    中文: 设置系统音量，取值范围为 0-100
    """
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume = ctypes.cast(interface, ctypes.POINTER(IAudioEndpointVolume))

    # 控制音量在 0.0 - 1.0 之间
    volume.SetMasterVolumeLevelScalar(value / 100, None)  # type: ignore


def notify_in_thread(message: str) -> None:
    """
    English: Displays a Windows toast notification in a separate thread
    中文: 在单独线程中显示 Windows toast 通知
    """
    logging.info(f"通知: {message}")
    def notify_message():
        notify(message)

    thread = threading.Thread(target=notify_message)
    thread.daemon = True
    thread.start()


"""
根据接收到的命令和主题来处理相应的操作。

参数:
- command: 接收到的命令
- topic: 命令的主题
"""


def process_command(command: str, topic: str) -> None:
    """
    English: Handles the command received from MQTT messages based on the given topic
    中文: 根据主题处理从 MQTT 消息接收到的命令
    """
    logging.info(f"处理命令: {command} 主题: {topic}")

    # 先判断应用程序或服务类型主题
    for application, directory in applications:
        if topic == application:
            if command == "off":
                process_name = os.path.basename(directory)
                logging.info(f"尝试终止进程: {process_name}")
                notify_in_thread(f"尝试终止进程: {process_name}")
                result = subprocess.run(
                    ["taskkill", "/F", "/IM", process_name],
                    capture_output=True,
                    text=True,
                )
                logging.info(result.stdout)
            elif command == "on":
                if not directory or not os.path.isfile(directory):
                    logging.error(f"启动失败，文件不存在: {directory}")
                    notify_in_thread(f"启动失败，文件不存在: {directory}")
                    return
                logging.info(f"启动: {directory}")
                subprocess.Popen(directory)
                notify_in_thread(f"启动: {directory}")
            return
    
    def check_service_status(service_name):
        result = subprocess.run(["sc", "query", service_name], capture_output=True, text=True)
        if "RUNNING" in result.stdout:
            logging.info(f"服务 {service_name} 正在运行")
            return "running"
        elif "STOPPED" in result.stdout:
            logging.info(f"服务 {service_name} 已停止")
            return "stopped"
        else:
            logging.error(f"无法获取服务{serve_name}的状态:{result.stderr}")
            return "unknown"
    
    for serve, serve_name in serves:
        if topic == serve:
            if command == "off":
                status = check_service_status(serve_name)
                if status == "unknown":
                    logging.error(f"无法获取服务{serve_name}的状态")
                    notify_in_thread(f"无法获取 {serve_name} 的状态,详情请查看日志")
                if status == "stopped":
                    logging.info(f"{serve_name} 还没有运行")
                    notify_in_thread(f"{serve_name} 还没有运行")
                else:
                    result = subprocess.run(["sc", "stop", serve_name], shell=True)
                    if result.returncode == 0:
                        logging.info(f"成功关闭 {serve_name}")
                        notify_in_thread(f"成功关闭 {serve_name}")
                    else:
                        logging.error(f"关闭 {serve_name} 失败")
                        logging.error(result.stderr)
                        notify_in_thread(f"关闭 {serve_name} 失败")
            elif command == "on":
                status = check_service_status(serve_name)
                if status == "unknown":
                    logging.error(f"无法获取服务{serve_name}的状态")
                    notify_in_thread(f"无法获取 {serve_name} 的状态,详情请查看日志")
                if status == "running":
                    logging.info(f"{serve_name} 已经在运行")
                    notify_in_thread(f"{serve_name} 已经在运行")
                else:
                    result = subprocess.run(["sc", "start", serve_name], shell=True)
                    if result.returncode == 0:
                        logging.info(f"成功启动 {serve_name}")
                        notify_in_thread(f"成功启动 {serve_name}")
                    else:
                        logging.error(f"启动 {serve_name} 失败")
                        logging.error(result.stderr)
                        notify_in_thread(f"启动 {serve_name} 失败")
            return

    # 若不匹配应用程序或服务，再判断是否为内置主题
    if topic == Computer:
        # 电脑开关机控制
        if command == "on":
            logging.info("执行锁屏操作")
            ctypes.windll.user32.LockWorkStation()
        elif command == "off":
            logging.info("60秒后执行重启操作")
            execute_command("shutdown -r -t 60")
            notify_in_thread("电脑将在60秒后重启")
    elif topic == screen:
        # 屏幕亮度控制
        if command == "off":
            logging.info("执行亮度最小化操作")
            set_brightness(0)
        elif command == "on":
            logging.info("执行亮度最大化操作")
            set_brightness(100)
        elif command.startswith("on#"):
            try:
                # 解析百分比值
                brightness = int(command.split("#")[1])
                logging.info(f"设置亮度: {brightness}")
                set_brightness(brightness)
            except ValueError:
                logging.error("亮度值无效")
                notify_in_thread("亮度值无效")
            except Exception as e:
                logging.error(f"设置亮度时出错: {e}")
                notify_in_thread(f"设置亮度时发生未知错误，请查看日志")
        else:
            logging.error(f"未知的亮度控制命令: {command}")
            notify_in_thread(f"未知的亮度控制命令: {command}")
    elif topic == volume:
        # 音量控制
        if command == "off":
            logging.info("执行音量最小化操作")
            set_volume(0)
        elif command == "on":
            logging.info("执行音量最大化操作")
            set_volume(100)
        elif command == "pause":
            # 播放/暂停
            logging.info("执行静音操作")
            set_volume(0)
        elif command.startswith("on#"):
            try:
                # 解析百分比值
                volume_value = int(command.split("#")[1])
                logging.info(f"设置音量: {volume_value}")
                set_volume(volume_value)
            except ValueError:
                logging.error("音量值无效")
                notify_in_thread("音量值无效")
            except Exception as e:
                logging.error(f"设置音量时出错: {e}")
                notify_in_thread(f"设置音量时发生未知错误，请查看日志")
        else:
            logging.error(f"未知的音量控制命令: {command}")
            notify_in_thread(f"未知的音量控制命令: {command}")
    elif topic == sleep:
        if command == "off":
            logging.info("执行关闭睡眠模式操作")
            notify_in_thread("当前还没有进入睡眠模式哦！")
        elif command == "on":
            logging.info("执行开启睡眠模式操作")
            execute_command("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
    elif topic == media:
        # 媒体控制（作为窗帘设备）
        try:
            if command == "off":
                # 下一曲
                logging.info("执行下一曲操作")
                pyautogui_press('nexttrack')
            elif command == "on":
                # 上一曲
                logging.info("执行上一曲操作")
                pyautogui_press('prevtrack')
            elif command == "pause":
                # 播放/暂停
                logging.info("执行播放/暂停操作")
                pyautogui_press('playpause')
            elif command.startswith("on#"):
                    # 解析百分比值
                    value = int(command.split("#")[1])
                    if value <= 33:
                        # 1-33：下一曲
                        logging.info(f"执行下一曲操作（百分比:{value}）")
                        pyautogui_press('nexttrack')
                    elif value <= 66:
                        # 34-66：播放/暂停
                        logging.info(f"执行播放/暂停操作（百分比:{value}）")
                        pyautogui_press('playpause')
                    else:
                        # 67-100：上一曲
                        logging.info(f"执行上一曲操作（百分比:{value}）")
                        pyautogui_press('prevtrack')
            else:
                logging.error(f"未知的媒体控制命令: {command}")
                notify_in_thread(f"未知的媒体控制命令: {command}")
        except Exception as e:
            logging.error(f"媒体控制执行失败: {e}")
            notify_in_thread(f"媒体控制执行失败，详情请查看日志")
    else:
        # 未知主题
        logging.error(f"未知主题: {topic}")
        notify_in_thread(f"未知主题: {topic}")


"""
MQTT接收到消息时的回调函数。

参数:
- client: MQTT客户端实例
- userdata: 用户数据
- message: 接收到的消息
"""


def on_message(client, userdata: list, message) -> None:
    """
    English: Callback when an MQTT message is received
    中文: MQTT接收到消息时的回调函数
    """
    userdata.append(message.payload)
    command = message.payload.decode()
    logging.info(f"'{message.topic}' 主题收到 '{command}'")
    process_command(command, message.topic)


"""
MQTT连接时的回调函数。

参数:
- client: MQTT客户端实例
- userdata: 用户数据
- flags: 连接标志
- reason_code: 连接结果的状态码
- properties: 属性
"""


def on_connect(client, userdata: list, flags: dict, reason_code, properties=None) -> None:
    # 兼容 int 和 ReasonCode 类型
    try:
        is_fail = reason_code.is_failure
    except AttributeError:
        is_fail = reason_code != 0

    if is_fail:
        notify_in_thread(
            f"连接MQTT失败: {reason_code}. 重新连接中..."
        )
        logging.error(f"连接失败: {reason_code}. loop_forever() 将重试连接")
    else:
        notify_in_thread(f"MQTT成功连接至{broker}")
        logging.info(f"连接到 {broker}")
        for key, value in config.items():
            if key.endswith("_checked") and value == 1:
                topic_key = key.replace("_checked", "")
                topic = config.get(topic_key)
                if topic:
                    client.subscribe(topic)
                    logging.info(f'订阅主题: "{topic}"')

def get_main_proc(process_name):
    """查找程序进程是否存在"""
    logging.info(f"执行函数: get_main_proc; 参数: {process_name}")
    
    # 如果不是管理员权限运行，可能无法查看所有进程，记录警告
    global IS_ADMIN
    if not IS_ADMIN:
        logging.warning("程序未以管理员权限运行,可能无法查看所有进程")
    if process_name.endswith('.exe'):
        logging.info(f"查找程序可执行文件: {process_name}")
        # 可执行文件查找方式
        target_user=None
        process_name = process_name.lower()
        target_user = target_user.lower() if target_user else None

        for proc in psutil.process_iter(['name', 'username']):
            try:
                # 获取进程信息
                proc_info = proc.info
                current_name = proc_info['name'].lower()
                current_user = proc_info['username']

                # 匹配进程名
                if current_name == process_name:
                    # 未指定用户则直接返回True
                    if target_user is None:
                        logging.info(f"找到程序进程: {proc.pid}, 用户: {current_user}")
                        return True
                    # 指定用户时提取用户名部分比较
                    if current_user:
                        user_part = current_user.split('\\')[-1].lower()
                        if user_part == target_user:
                            logging.info(f"找到程序进程: {proc.pid}, 用户: {current_user}")
                            return True
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                logging.error(f"获取进程信息失败: {proc.pid}")
                continue
        # 如果找不到进程，记录信息
        logging.info(f"未找到程序进程: {process_name}")
        return None
    else:
        # Python脚本查找方式
        logging.info(f"查找Python脚本主程序: {process_name}")
        # 尝试查找命令行中包含脚本名的Python进程
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'username']):
            try:
                proc_info = proc.info
                if proc_info['name'] and proc_info['name'].lower() in ('python.exe', 'pythonw.exe'):
                    cmdline = ' '.join(proc_info['cmdline']) if proc_info['cmdline'] else ""
                    if process_name in cmdline:
                        logging.info(f"找到程序Python进程: {proc.pid}, 命令行: {cmdline}")
                        return proc
            except (psutil.AccessDenied, psutil.NoSuchProcess, Exception) as e:
                logging.error(f"获取Python进程信息失败: {e}")
                continue
        
        # 如果常规方法找不到，尝试使用wmic命令行工具
        logging.info("常规方法未找到Python进程，尝试使用wmic命令行工具")
        try:
            cmd = 'wmic process where "name=\'python.exe\' or name=\'pythonw.exe\'" get ProcessId,CommandLine /value'
            result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
            lines = result.stdout.strip().split('\n')
            
            current_pid = None
            current_cmd = None
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                    
                if line.startswith("CommandLine="):
                    current_cmd = line[12:]
                elif line.startswith("ProcessId="):
                    current_pid = line[10:]
                    
                    if current_cmd and current_pid and process_name in current_cmd:
                        try:
                            logging.info(f"wmic找到程序Python进程: {current_pid}, 命令行: {current_cmd}")
                            return psutil.Process(int(current_pid))
                        except (psutil.NoSuchProcess, ValueError) as e:
                            logging.error(f"获取进程对象失败，PID: {current_pid}, 错误: {e}")
                    
                    current_pid = None
                    current_cmd = None
        except Exception as e:
            logging.error(f"使用wmic查找Python进程失败: {e}")
    
    logging.info("未找到程序进程")
    return None



def run_as_admin(executable_path, parameters=None, working_dir=None, show_cmd=0):
    """
    以管理员权限运行指定程序

    参数：
    executable_path (str): 要执行的可执行文件路径
    parameters (str, optional): 传递给程序的参数，默认为None
    working_dir (str, optional): 工作目录，默认为None（当前目录）
    show_cmd (int, optional): 窗口显示方式，默认为0（1正常显示，0隐藏）

    返回：
    int: ShellExecute的返回值，若小于等于32表示出错
    """
    logging.info(f"执行函数: run_as_admin；参数: {executable_path}")
    if parameters is None:
        parameters = ''
    if working_dir is None:
        working_dir = ''
    # 调用ShellExecuteW，设置动词为'runas'
    result = ctypes.windll.shell32.ShellExecuteW(
        None,                  # 父窗口句柄
        'runas',               # 操作：请求管理员权限
        executable_path,       # 要执行的文件路径
        parameters,            # 参数
        working_dir,           # 工作目录
        show_cmd               # 窗口显示方式
    )
    
    return result

def run_py_in_venv_as_admin_hidden(python_exe_path, script_path, script_args=None):
    """
    使用指定的 Python 解释器（如虚拟环境中的 python.exe）以管理员权限静默运行脚本
    
    参数：
    python_exe_path (str): Python 解释器路径
    script_path (str): 要运行的 Python 脚本路径
    script_args (list): 传递给脚本的参数（可选）
    """
    logging.info(f"执行函数: run_py_in_venv_as_admin_hidden；参数: {python_exe_path}, {script_path}")
    if not os.path.exists(python_exe_path):
        raise FileNotFoundError(f"Python 解释器未找到: {python_exe_path}")

    if script_args is None:
        script_args = []

    # 构造命令（确保路径带引号，防止空格问题）
    command = f'"{python_exe_path}" "{script_path}" {" ".join(script_args)}'
    logging.info(f"构造的命令: {command}")

    # 使用 ShellExecuteW 以管理员权限静默运行
    result = ctypes.windll.shell32.ShellExecuteW(
        None,               # 父窗口句柄
        'runas',            # 请求管理员权限
        'cmd.exe',          # 通过 cmd 执行（但隐藏窗口）
        f'/c {command}',    # /c 执行后关闭窗口
        None,               # 工作目录
        0                   # 窗口模式：0=隐藏
    )
    return result

def restart_self_as_admin():
    """以管理员权限重新启动当前程序"""
    logging.info("执行函数: restart_self_as_admin")
    try:
        # 获取当前程序的完整路径和参数
        if getattr(sys, "frozen", False):
            # 如果是打包后的exe
            current_exe = sys.executable
            logging.info(f"当前程序路径(EXE): {current_exe}")
        else:
            # 如果是Python脚本
            current_script = os.path.abspath(__file__)
            current_exe = sys.executable
            logging.info(f"当前程序路径(脚本): {current_script}")
            logging.info(f"Python解释器路径: {current_exe}")
        
        # 构建重启命令
        if getattr(sys, "frozen", False):
            # EXE模式：直接以管理员权限运行exe
            result = run_as_admin(current_exe)
        else:
            # 脚本模式：以管理员权限运行Python脚本
            result = run_py_in_venv_as_admin_hidden(current_exe, os.path.abspath(__file__))
        
        if result > 32:
            logging.info(f"成功以管理员权限重启程序，返回值: {result}")
            # 重启成功，退出当前进程
            logging.info("正在退出当前进程...")
            os._exit(0)
        else:
            logging.error(f"以管理员权限重启程序失败，错误码: {result}")
            messagebox.showwarning("UAC提权", f"获取管理员权限失败，错误码: {result}")
            return False
            
    except Exception as e:
        logging.error(f"重启程序时出错: {e}")
        messagebox.showerror("UAC提权", f"重启程序时出错: {e}")
        return False

def check_and_request_uac():
    """检查并在需要时请求提权"""
    logging.info("执行函数: check_and_request_uac")
    
    # 如果已经是管理员权限，无需提权
    if IS_ADMIN:
        logging.info("当前已具有管理员权限，无需提权")
        return True
    
    logging.info("当前程序未获得管理员权限，准备提权...")
    
    try:
        # 询问用户是否要提权
        if messagebox.askyesno("管理员权限", "程序未获得管理员权限。\n是否立即请求管理员权限？\n\n选择'是'将重新启动程序并请求管理员权限。"):
            # 以管理员权限重新启动程序
            return restart_self_as_admin()
        else:
            logging.info("用户选择不进行提权")
            return False
        
    except Exception as e:
        logging.error(f"提权过程中出错: {e}")
        messagebox.showerror("管理员权限", f"提权失败: {e}")
        return False

def startup_admin_check():
    """启动时进行管理员权限检查和自动提权"""
    logging.info("开始检查管理员权限状态...")
    try:
        # 检查并请求提权（如果需要的话）
        admin_result = check_and_request_uac()
        if admin_result is False:  # 明确检查False，因为None表示其他情况
            logging.info("未进行提权或提权失败，程序将以当前权限继续运行")
        # 如果admin_result是True，说明已经有管理员权限
        # 如果函数内部重启了程序，这里的代码不会执行到
    except Exception as e:
        logging.error(f"管理员权限检查过程中出现异常: {e}")
        logging.info("程序将以当前权限继续运行")


def open_gui() -> None:
    """
    English: Attempts to open GUI.py or RC-GUI.exe, else shows an error message
    中文: 尝试运行 GUI.py 或 RC-GUI.exe，如果找不到则弹出错误提示
    """
    if os.path.isfile("GUI.py"):
        logging.info("正在打开配置窗口...")
        subprocess.Popen([".venv\\Scripts\\python.exe", "GUI.py"])
        # notify_in_thread("正在打开配置窗口...")
    elif os.path.isfile("RC-GUI.exe"):
        logging.info("正在打开配置窗口...")
        subprocess.Popen(["RC-GUI.exe"])
        # notify_in_thread("正在打开配置窗口...")
    else:
        def show_message():
            current_path = os.getcwd()
            logging.error(f"找不到GUI.py或RC-GUI.exe\n当前工作路径{current_path}")
            messagebox.showerror(
                "Error", f"找不到GUI.py或RC-GUI.exe\n当前工作路径{current_path}"
            )

        thread = threading.Thread(target=show_message)
        thread.daemon = True
        thread.start()


"""
退出程序。

无参数
无返回值
"""


def exit_program() -> None:
    """
    English: Stops the MQTT loop and exits the program
    中文: 停止 MQTT 循环，并退出程序
    """
    logging.info("正在退出程序...")
    try:
        mqttc.loop_stop()
        mqttc.disconnect()
    except Exception as e:
        logging.error(f"程序停止时出错: {e}")
    finally:
        try:
            ctypes.windll.kernel32.ReleaseMutex(mutex)
            ctypes.windll.kernel32.CloseHandle(mutex)
            logging.info("互斥体已释放")
        except Exception as e:
            logging.error(f"释放互斥体时出错: {e}")
        
        logging.info("程序已停止")
        threading.Timer(0.5, lambda: os._exit(0)).start()
        sys.exit(0)

# 获取资源文件的路径
def resource_path(relative_path):
    """获取资源文件的绝对路径"""
    # PyInstaller 创建临时文件夹
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)

# 获取应用程序的路径
if getattr(sys, "frozen", False):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

# 改变当前的工作路径
os.chdir(application_path)

# 配置文件和日志文件路径改为当前工作目录
appdata_path = os.path.abspath(os.path.dirname(sys.argv[0]))
logs_dir = os.path.join(appdata_path, "logs")

# 确保日志目录存在
if not os.path.exists(logs_dir):
    try:
        os.makedirs(logs_dir)
    except Exception as e:
        print(f"创建日志目录失败: {e}")
        logs_dir = appdata_path

log_path = os.path.join(logs_dir, "RC.log")
config_path = os.path.join(appdata_path, "config.json")

# 配置日志处理器，启用日志轮转
log_handler = RotatingFileHandler(
    log_path, 
    maxBytes=1*1024*1024,  # 1MB
    backupCount=1,          # 保留1个备份文件
    encoding='utf-8'
)

# 设置日志格式
log_formatter = logging.Formatter(
    '%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s',
    datefmt="%Y-%m-%d %H:%M:%S"
)
log_handler.setFormatter(log_formatter)

# 获取根日志记录器并设置
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(log_handler)

# 检查程序是以脚本形式运行还是打包后的exe运行
is_script_mode = not getattr(sys, "frozen", False)
if is_script_mode:
    # 如果是脚本形式运行，先清空日志文件
    try:
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write('')  # 清空文件内容
        logging.info(f"已清空日志文件: {log_path}")
        print(f"已清空日志文件: {log_path}")
    except Exception as e:
        logging.error(f"清空日志文件失败: {e}")
        print(f"清空日志文件失败: {e}")

# 记录程序启动信息
logging.info("=" * 50)
logging.info("程序启动")
logging.info(f"当前工作目录: {os.getcwd()}")
logging.info(f"日志文件路径: {log_path}")
logging.info(f"配置文件路径: {config_path}")
logging.info(f"Python版本: {sys.version}")
logging.info("=" * 50)

# 在程序启动时查询托盘程序的管理员权限状态并保存为全局变量
IS_ADMIN = False
try:
    IS_ADMIN = ctypes.windll.shell32.IsUserAnAdmin() != 0
    logging.info(f"管理员权限状态: {'已获得' if IS_ADMIN else '未获得'}")
except Exception as e:
    logging.error(f"检查管理员权限时出错: {e}")
    IS_ADMIN = False


# 检查配置文件是否存在
if os.path.exists(config_path):
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError:
        messagebox.showerror("Error", "配置文件格式错误\n请检查config.json文件")
        logging.error("config.json 文件格式错误")
        open_gui()
        threading.Timer(0.5, lambda: os._exit(0)).start()
        sys.exit()
else:
    messagebox.showerror("Error", "配置文件不存在\n请先打开RC-GUI配置文件")
    logging.error("config.json 文件不存在")
    open_gui()
    threading.Timer(0.5, lambda: os._exit(0)).start()
    sys.exit()


# 确保config已经定义后再继续
if config.get("test") == 1:
    logging.warning("开启测试模式:可以不启用任何主题")
else:
    if (
        all(
            config.get(f"{key}_checked", 0) == 0
            for key in ["Computer", "screen", "volume", "sleep"]
        )
        and all(
            config.get(f"application{index}_checked", 0) == 0
            for index in range(1, 100)
        )
        and all(
            config.get(f"serve{index}_checked", 0) == 0 for index in range(1, 100)
        )
    ):
        logging.error("没有启用任何主题，显示错误信息")
        messagebox.showerror("Error", "主题不能一个都没有吧！\n（除了测试模式）")
        open_gui()
        logging.info("程序已停止")
        threading.Timer(0.5, lambda: os._exit(0)).start()
        sys.exit(0)
    else:
        logging.info("至少已有一个主题被启用")

broker = config.get("broker")
secret_id = config.get("secret_id")
port = int(config.get("port"))


# 动态加载主题
def load_theme(key):
    """
    English: Loads the theme from config if it is enabled
    中文: 如果主题被勾选启用，则从配置中加载该主题
    """
    return config.get(key) if config.get(f"{key}_checked") == 1 else None


Computer = load_theme("Computer")
screen = load_theme("screen")
volume = load_theme("volume")
sleep = load_theme("sleep")
media = load_theme("media")

# 加载应用程序主题到应用程序列表
applications = []
for i in range(1, 50):
    app_key = f"application{i}"
    directory_key = f"application{i}_directory{i}"
    application = load_theme(app_key)
    directory = config.get(directory_key) if application else None
    if application:
        logging.info(f"加载应用程序: {app_key}, 目录: {directory}")
        applications.append((application, directory))
logging.info(f"读取的应用程序列表: {applications}\n")

# 加载服务主题到服务列表
serves = []
for i in range(1, 50):
    serve_key = f"serve{i}"
    serve_name_key = f"serve{i}_value"
    serve = load_theme(serve_key)
    serve_name = config.get(serve_name_key) if serve else None
    if serve:
        logging.info(f"加载服务: {serve_key}, 名称: {serve_name}")
        serves.append((serve, serve_name))
logging.info(f"读取的服务列表: {serves}\n")

# 如果主题不为空，将其记录到日志中
for key in ["Computer", "screen", "volume", "sleep", "media"]:
    if config.get(key):
        logging.info(f'主题"{config.get(key)}"')

for application, directory in applications:
    logging.info(f'主题"{application}"，值："{directory}"')

for serve, serve_name in serves:
    logging.info(f'主题"{serve}"，值："{serve_name}"')
    
"""
托盘图标

"""
def tray() -> None:
    try:
        global IS_ADMIN
        admin_status = "【已获得管理员权限】" if IS_ADMIN else "【未获得管理员权限】"
        logging.info(f"开始加载托盘图标，当前权限状态: {admin_status}")
        # 初始化系统托盘图标和菜单
        icon_path = resource_path("icon.ico" if getattr(sys, "frozen", False) else "res\\icon.ico")
        # 从资源文件中读取图像
        with open(icon_path, "rb") as f:
            image_data = f.read()
        icon = pystray.Icon("RC-main", title=f"远程控制-{BANBEN}")
        image = Image.open(io.BytesIO(image_data))
        menu = (
            pystray.MenuItem(f"{admin_status}", None),
            pystray.MenuItem("打开配置", open_gui),
            pystray.MenuItem("退出", exit_program),
        )
        icon.menu = menu
        icon.icon = image
        icon_Thread = threading.Thread(target=icon.run)
        icon_Thread.daemon = True
        icon_Thread.start()
        logging.info("托盘图标已加载完成")
    except Exception as e:
        messagebox.showerror(
            "Error", f"加载托盘图标时出错\n详情请查看日志"
        )
        logging.error(f"加载托盘图标时出错: {e}")


def check_tray_and_start():
    """
    检测托盘程序是否运行，如果未运行则启动自带托盘
    """
    TRAY_EXE_NAME = "RC-tray.exe" if getattr(sys, "frozen", False) else "tray.py"
    tray_zt = get_main_proc(TRAY_EXE_NAME)
    if not tray_zt:
        logging.error("托盘未启动，将使用自带托盘")
        tray()
        notify_in_thread("托盘未启动，将使用自带托盘")
    else:
        logging.info("托盘进程已存在")

def tray_():
    """
    延迟1秒后检测托盘状态，不阻塞主进程
    """
    logging.info("将在1秒后检测托盘程序状态")
    timer = threading.Timer(1.0, check_tray_and_start)
    timer.daemon = True
    timer.start()

# 启动时检查管理员权限并请求提权
check_and_request_uac()

tray_()

if IS_ADMIN:
    logging.info("当前程序以管理员权限运行")
    # 将管理员权限状态写入文件，方便其他程序查询
    try:
        status_file = os.path.join(logs_dir, "admin_status.txt")
        with open(status_file, "w", encoding="utf-8") as f:
            f.write("admin=1")
        logging.info(f"管理员权限状态已写入文件: {status_file}")
    except Exception as e:
        logging.error(f"写入管理员权限状态文件失败: {e}")
else:
    logging.info("当前程序以普通权限运行")
    # 将普通权限状态写入文件
    try:
        status_file = os.path.join(logs_dir, "admin_status.txt")
        with open(status_file, "w", encoding="utf-8") as f:
            f.write("admin=0")
        logging.info(f"权限状态已写入文件: {status_file}")
    except Exception as e:
        logging.error(f"写入权限状态文件失败: {e}")

# 初始化MQTT客户端
mqttc = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2) # type: ignore
mqttc.on_connect = on_connect
mqttc.on_message = on_message
mqttc.on_subscribe = on_subscribe
mqttc.on_unsubscribe = on_unsubscribe

mqttc.user_data_set([])
mqttc._client_id = secret_id
try:
    mqttc.connect(broker, port)
except socket.timeout:
    messagebox.showerror(
        "Error", "连接到 MQTT 服务器超时，请检查网络连接或服务器地址，端口号！"
    )
    open_gui()
    threading.Timer(0.5, lambda: os._exit(0)).start()
except socket.gaierror:
    messagebox.showerror(
        "Error", "无法解析 MQTT 服务器地址，请重试或检查服务器地址是否正确！"
    )
    open_gui()
    threading.Timer(0.5, lambda: os._exit(0)).start()
try:
    mqttc.loop_forever()
except KeyboardInterrupt:
    logging.warning("收到中断,程序停止")
    notify_in_thread("收到中断信号\n程序停止")
    exit_program()
except Exception as e:
    logging.error(f"程序异常: {e}")
    exit_program()

logging.info(f"总共收到以下消息: {mqttc.user_data_get()}")

try:
    logging.info("释放互斥体")
    ctypes.windll.kernel32.ReleaseMutex(mutex)
    ctypes.windll.kernel32.CloseHandle(mutex)
except Exception as e:
    logging.error(f"释放互斥体时出错: {e}")
