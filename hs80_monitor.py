# hs80_monitor_final.py
import hid
import time
import sys
import threading
import psutil
from datetime import datetime
import pystray
from PIL import Image, ImageDraw
import traceback

# Forzar inclusion de appdirs para PyInstaller
try:
    import appdirs
    _appdirs_user_data_dir = appdirs.user_data_dir
except:
    pass

class HS80CorsairProtocol:
    def is_icue_running(self):
        """Detecta si iCUE está ejecutándose"""
        for proc in psutil.process_iter(['name']):
            try:
                if proc.info['name'].lower() == 'icue.exe':
                    return True
            except:
                pass
        return False
    def __init__(self):
        self.vendor_id = 0x1b1c
        self.product_id = 0x0a6b
        self.device = None
        self.is_connected = False
        
        self.COMMANDS = {
            'BATTERY_LEVEL': [0x02, 0x09, 0x02, 0x0F, 0x00],  # 0x09 = wireless mode
            'BATTERY_STATUS': [0x02, 0x09, 0x02, 0x10, 0x00],
        }
        
        self.CHARGING_STATES = {
            1: "Charging",
            2: "Discharging", 
            3: "Fully Charged",
            4: "Charging"  # Idle = cargando también
        }
        
        # Cache para reducir lecturas
        self.last_read_time = 0
        self.last_battery_info = None
        self.read_cooldown = 10000  # 10 segundos mínimo entre lecturas reales
        
        # Estadísticas
        self.read_count = 0
        self.error_count = 0
    
    def connect(self) -> bool:
        """Conecta al dispositivo HS80"""
        try:
            print("🔍 Buscando dispositivo...")
            
            for dev in hid.enumerate():
                if dev['vendor_id'] == self.vendor_id and dev['product_id'] == self.product_id:
                    print(f"  → Encontrado: VID={hex(dev['vendor_id'])}, PID={hex(dev['product_id'])}")
                    print(f"     Interface: {dev.get('interface_number')}")
                    print(f"     Usage Page: {hex(dev.get('usage_page', 0))}")
                    
                    self.device = hid.device()
                    self.device.open_path(dev['path'])
                    self.device.set_nonblocking(1)
                    self.is_connected = True
                    
                    # Pequeña pausa para estabilizar
                    time.sleep(0.1)
                    
                    print("✅ Conectado exitosamente")
                    return True
            
            print("❌ No se encontró el dispositivo HS80")
            return False
            
        except Exception as e:
            print(f"❌ Error conectando: {e}")
            return False
    
    def _send_command(self, command: list, expected_response_len=64):
        """Envía comando HID y lee respuesta"""
        if not self.device or not self.is_connected:
            return None
        
        try:
            # DEBUG: Mostrar comando
            hex_cmd = ' '.join(f'{b:02x}' for b in command[:8])
            # print(f"  TX: {hex_cmd}...")
            
            # Crear paquete de 64 bytes
            packet = command + [0x00] * (64 - len(command))
            
            # Limpiar buffer de lectura
            try:
                while self.device.read(64):
                    pass
            except:
                pass
            
            # Enviar comando
            bytes_written = self.device.write(bytes(packet))
            if bytes_written != 64:
                print(f"  ⚠️ Solo se escribieron {bytes_written}/64 bytes")
            
            # Pequeña pausa
            time.sleep(0.1)
            
            # Leer respuesta (intentar varias veces)
            max_attempts = 10
            for attempt in range(max_attempts):
                try:
                    data = self.device.read(expected_response_len)
                    if data:
                        data_list = list(data)
                        hex_data = ' '.join(f'{b:02x}' for b in data_list[:12])
                        # print(f"  RX [{attempt+1}]: {hex_data}...")
                        self.read_count += 1
                        return data_list
                    time.sleep(0.02)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        print(f"  ⚠️ Error leyendo respuesta: {e}")
            
            print(f"  ⚠️ Sin respuesta después de {max_attempts} intentos")
            return None
            
        except Exception as e:
            print(f"  ❌ Error en _send_command: {e}")
            self.error_count += 1
            return None
    
    def get_battery_info(self, force_read=False):
        """Obtiene información de batería - VERSIÓN CON MODO HÍBRIDO"""
        
        # Usar cache si no es lectura forzada
        current_time = time.time() * 1000  # milisegundos
        if (not force_read and self.last_battery_info and 
            current_time - self.last_read_time < self.read_cooldown):
            return self.last_battery_info
        
        if not self.is_connected:
            if not self.connect():
                return {"error": "Dispositivo no conectado"}
        
        # Detectar si iCUE está activo
        is_icue = self.is_icue_running()
        mode_label = "[iCUE]" if is_icue else "[Normal]"
        
        try:
            print(f"  📊 Leyendo batería... {mode_label}")
            
            # 1. Leer NIVEL de batería (comando 0x0F)
            level_data = self._send_command(self.COMMANDS['BATTERY_LEVEL'])
            if not level_data:
                return {"error": "No se pudo leer nivel de batería"}
            
            # Verificar longitud mínima
            if len(level_data) < 8:
                print(f"  ⚠️ Respuesta muy corta: {len(level_data)} bytes")
                return {"error": f"Respuesta muy corta ({len(level_data)} bytes)"}
            
            # DEBUG: Mostrar datos crudos
            hex_data = ' '.join(f'{b:02x}' for b in level_data[:16])
            print(f"  🔢 Datos nivel: {hex_data}")
            
            # Decodificar según modo
            battery_percent, decoded_ok = self._icue_mode_decode(level_data, is_icue)
            
            # Reintentos si datos no válidos (máx 5 intentos)
            max_retries = 5
            retry_count = 0
            while not decoded_ok and retry_count < max_retries and is_icue:
                retry_count += 1
                time.sleep(0.3)
                level_data = self._send_command(self.COMMANDS['BATTERY_LEVEL'])
                if level_data and len(level_data) >= 8:
                    battery_percent, decoded_ok = self._icue_mode_decode(level_data, is_icue)
                    if decoded_ok:
                        hex_data = ' '.join(f'{b:02x}' for b in level_data[:16])
                        print(f"  🔄 Reintento exitoso: {hex_data}")
            
            if not decoded_ok:
                # Verificar si hay datos en cache y no son muy antiguos (< 2 minutos)
                if self.last_battery_info:
                    cache_age = time.time() * 1000 - self.last_read_time
                    if cache_age < 120000:  # 2 minutos
                        print(f"  ⚠️ Sin datos válidos, usando cache ({self.last_battery_info['percentage']}%)")
                        return self.last_battery_info
                # Cache muy antiguo o no existe
                print(f"  ❌ Sin datos válidos y cache expirado")
                return {"error": "Sin respuesta del dispositivo", "disconnected": True}
            
            if battery_percent is None:
                battery_percent = 50
            
            if battery_percent is None:
                battery_percent = 50
            
            print(f"  🔋 Nivel: {battery_percent:.1f}%")
            
            # 2. Leer ESTADO de carga (comando 0x10)
            # Reintentar si el byte2 no es válido (igual que con nivel)
            status_data = None
            for _ in range(3):
                temp_status = self._send_command(self.COMMANDS['BATTERY_STATUS'])
                if temp_status and len(temp_status) >= 5 and temp_status[2] == 0x02:
                    status_data = temp_status
                    break
                time.sleep(0.1)
            
            if not status_data:
                # Usar cache si existe
                if self.last_battery_info:
                    charging_state = self.last_battery_info.get('charging_state', 2)
                else:
                    charging_state = 2
            else:
                charging_state = status_data[4]
                print(f"  ⚡ Estado: {charging_state} ({self.CHARGING_STATES.get(charging_state, 'Unknown')})")
            
            # Validar rango
            if battery_percent < 0 or battery_percent > 100:
                print(f"  ⚠️ Porcentaje inválido: {battery_percent}%")
                battery_percent = 50
            
            # Crear resultado
            result = {
                "percentage": max(0.0, min(100.0, round(battery_percent, 1))),
                "raw_level": int(battery_percent * 10),
                "charging_state": charging_state,
                "charging_text": self.CHARGING_STATES.get(charging_state, "Unknown"),
                "is_charging": charging_state in [1, 4],
                "is_fully_charged": charging_state == 3,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "raw_data": hex_data[:30] + "..." if len(hex_data) > 30 else hex_data,
                "mode": mode_label
            }
            
            # Actualizar cache
            self.last_battery_info = result
            self.last_read_time = current_time
            
            print(f"  ✅ Resultado: {result['percentage']}% ({result['charging_text']}) {mode_label}")
            return result
            
        except Exception as e:
            print(f"  ❌ Error en get_battery_info: {e}")
            traceback.print_exc()
            return {"error": str(e)}
    
    def _icue_mode_decode(self, data, is_icue_active):
        """Decodifica según el modo (iCUE abierto o cerrado)"""
        if len(data) < 8:
            return None, False
        
        byte2 = data[2]  # Indicador de validez (posición 2, no 3!)
        
        if not is_icue_active:
            # Modo normal: bytes 4-7 como int32 little-endian
            battery_raw = data[4:8]
            value = self._read_int32_little_endian(battery_raw)
            return value / 10.0, True
        else:
            # Modo iCUE: verificar si datos son válidos
            # byte[2] = 0x02 → datos válidos
            # byte[2] = 0x06 → datos inconsistentes (ignorar)
            
            if byte2 == 0x06:
                # Datos no válidos, devolver señal para reintentar
                return None, False
            
            # Datos válidos (byte2 == 0x02): bytes 4-7 como int32
            battery_raw = data[4:8]
            value = self._read_int32_little_endian(battery_raw)
            return value / 10.0, True

    def _alternative_decode(self, data):
        """Método alternativo de decodificación si el principal falla"""
        return self._icue_mode_decode(data, False)
    
    def _read_int32_little_endian(self, array):
        """Lee int32 little endian - CORREGIDO"""
        if len(array) < 4:
            print(f"  ⚠️ Array muy corto para int32: {len(array)} bytes")
            return 0
        
        # Asegurarse de que tenemos exactamente 4 bytes
        if len(array) > 4:
            array = array[:4]
        
        # Little endian: byte[0] es LSB, byte[3] es MSB
        value = (array[0] & 0xFF) | \
                ((array[1] & 0xFF) << 8) | \
                ((array[2] & 0xFF) << 16) | \
                ((array[3] & 0xFF) << 24)
        
        # Manejar signo si es negativo (complemento a 2)
        if value & 0x80000000:
            value = -((~value + 1) & 0xFFFFFFFF)
        
        return value
    
    def close(self):
        if self.device:
            try:
                self.device.close()
            except:
                pass
        self.is_connected = False

class HS80TrayMonitor:
    def __init__(self):
        self.protocol = HS80CorsairProtocol()
        self.tray_icon = None
        self.monitoring = False
        self.update_thread = None
        
        # Cargar preferencias desde archivo
        self._load_preferences()
        
        # Intervalo de actualización (segundos)
        self.INTERVAL_OPTIONS = [3, 5, 10, 15, 30, 60]
        
        # Localización
        self.lang = "ES"
        self.translations = {
            "ES": {
                "charging": "Cargando",
                "discharging": "Descargando",
                "fully_charged": "Completado",
                "idle": "Cargando",
                "unknown": "Desconocido",
                "disconnected": "Desconectado",
                "error": "Error",
                "update_now": "Actualizar ahora",
                "interval": "Intervalo",
                "language": "Idioma",
                "exit": "Salir"
            },
            "EN": {
                "charging": "Charging",
                "discharging": "Discharging",
                "fully_charged": "Full",
                "idle": "Charging",
                "unknown": "Unknown",
                "disconnected": "Disconnected",
                "error": "Error",
                "update_now": "Update now",
                "interval": "Interval",
                "language": "Language",
                "exit": "Exit"
            }
        }
        
        # Estado actual
        self.current_level = 0
        self.current_status = "Desconectado"
        
        # Notificaciones
        self.low_battery_notified = False
        self.critical_battery_notified = False
        self.LOW_THRESHOLD = 20
        self.CRITICAL_THRESHOLD = 10
        
        # Crear iconos
        self.icons = self._create_simple_icons()
    
    def _load_preferences(self):
        """Carga preferencias desde archivo simple"""
        import os
        
        # Valores por defecto
        self.lang = "ES"
        self.update_interval = 30
        
        # Buscar archivo de preferencias
        possible_paths = [
            "preferences.ini",
            os.path.join(os.path.dirname(__file__), "preferences.ini"),
            os.path.join(os.path.dirname(sys.executable), "preferences.ini")
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        content = f.read()
                    for line in content.split('\n'):
                        if '=' in line:
                            key, value = line.strip().split('=', 1)
                            if key == 'language':
                                self.lang = value.strip()
                            elif key == 'update_interval':
                                self.update_interval = int(value.strip())
                    break
                except:
                    pass
    
    def _save_preferences(self):
        """Guarda preferencias en archivo simple"""
        import os
        
        content = f"language={self.lang}\nupdate_interval={self.update_interval}\nauto_start=0\n"
        
        possible_paths = [
            "preferences.ini",
            os.path.join(os.path.dirname(sys.executable), "preferences.ini")
        ]
        
        for path in possible_paths:
            try:
                with open(path, 'w') as f:
                    f.write(content)
                break
            except:
                pass
    
    def t(self, key):
        """Traduce una clave al idioma actual"""
        return self.translations[self.lang].get(key, key)
    
    def _create_simple_icons(self):
        """Crea iconos simples"""
        icons = {}
        
        # Iconos por porcentaje (0, 10, 20, ..., 100)
        for level in range(0, 101, 10):
            icons[level] = self._create_battery_icon(level)
        
        # Iconos especiales
        icons['charging'] = self._create_charging_icon()
        icons['error'] = self._create_error_icon()
        icons['disconnected'] = self._create_disconnected_icon()
        
        return icons
    
    def _create_battery_icon(self, level):
        image = Image.new('RGB', (64, 64), (40, 40, 40))
        draw = ImageDraw.Draw(image)
        
        # Color según nivel
        if level >= 70:
            color = (0, 255, 0)      # Verde
        elif level >= 40:
            color = (255, 255, 0)    # Amarillo
        elif level >= 20:
            color = (255, 165, 0)    # Naranja
        else:
            color = (255, 0, 0)      # Rojo
        
        # Contorno de batería
        draw.rectangle([10, 22, 50, 42], outline=(200, 200, 200), width=2)
        draw.rectangle([50, 26, 54, 38], fill=(200, 200, 200))
        
        # Nivel de batería
        if level > 0:
            fill_width = int(38 * (level / 100))
            draw.rectangle([12, 24, 12 + fill_width, 40], fill=color)
        
        # Texto del porcentaje
        text = str(level)
        text_width = len(text) * 4
        draw.text((32 - text_width/2, 48), text, fill=(255, 255, 255))
        
        return image
    
    def _create_charging_icon(self):
        image = Image.new('RGB', (64, 64), (40, 40, 40))
        draw = ImageDraw.Draw(image)
        
        # Batería
        draw.rectangle([10, 22, 50, 42], outline=(0, 200, 255), width=2)
        draw.rectangle([50, 26, 54, 38], fill=(0, 200, 255))
        
        # Rayo de carga
        draw.polygon([(30, 25), (25, 35), (30, 35), (35, 45), (30, 45), (35, 35)], 
                     fill=(0, 200, 255))
        
        draw.text((32, 48), "Carg", fill=(255, 255, 255))
        
        return image
    
    def _create_error_icon(self):
        image = Image.new('RGB', (64, 64), (40, 40, 40))
        draw = ImageDraw.Draw(image)
        
        # Triángulo de advertencia
        draw.polygon([(32, 20), (20, 44), (44, 44)], outline=(255, 50, 50), width=2)
        
        # Signo de exclamación
        draw.rectangle([31, 26, 33, 36], fill=(255, 50, 50))
        draw.rectangle([31, 40, 33, 42], fill=(255, 50, 50))
        
        draw.text((32, 48), "Error", fill=(255, 255, 255))
        
        return image
    
    def _create_disconnected_icon(self):
        image = Image.new('RGB', (64, 64), (40, 40, 40))
        draw = ImageDraw.Draw(image)
        
        # Batería tachada
        draw.rectangle([10, 22, 50, 42], outline=(150, 150, 150), width=2)
        draw.rectangle([50, 26, 54, 38], fill=(150, 150, 150))
        
        # Cruz
        draw.line([14, 26, 46, 38], fill=(255, 80, 80), width=3)
        draw.line([46, 26, 14, 38], fill=(255, 80, 80), width=3)
        
        draw.text((32, 48), "Descon", fill=(255, 255, 255))
        
        return image
    
    def on_update_click(self, icon, item):
        """Manejador para 'Actualizar ahora'"""
        print("\n🔁 Actualización MANUAL solicitada")
        result = self.protocol.get_battery_info(force_read=True)
        self._process_battery_result(result)
    
    def on_interval_click(self, icon, item):
        """Manejador para cambiar intervalo"""
        self.update_interval = item.seconds
        print(f"\n⏱️ Intervalo cambiado a {self.update_interval} segundos")
    
    def _set_interval(self, seconds):
        """Establece el intervalo de actualización"""
        self.update_interval = seconds
        self._save_preferences()
        print(f"\n⏱️ Intervalo cambiado a {seconds} segundos")
        self._rebuild_menu()
    
    def _make_interval_handler(self, seconds):
        """Crea un manejador de intervalo"""
        def handler(icon, item):
            self._set_interval(seconds)
        return handler
    
    def _make_lang_handler(self, lang):
        """Crea un manejador de idioma"""
        def handler(icon, item):
            self.lang = lang
            self._save_preferences()
            print(f"\n🌐 Idioma cambiado a {lang}")
            self._rebuild_menu()
        return handler
    
    def _rebuild_menu(self):
        """Reconstruye el menú con el idioma actual"""
        # Menú de intervalo
        interval_items = []
        for sec in self.INTERVAL_OPTIONS:
            label = f"{sec} seg" if sec < 60 else "1 min"
            if sec == self.update_interval:
                label = f"✓ {label}"
            interval_items.append(pystray.MenuItem(label, self._make_interval_handler(sec)))
        interval_menu = pystray.Menu(*interval_items)
        
        # Menú de idioma
        lang_items = [
            pystray.MenuItem("✓ Español" if self.lang == "ES" else "Español", self._make_lang_handler("ES")),
            pystray.MenuItem("✓ English" if self.lang == "EN" else "English", self._make_lang_handler("EN"))
        ]
        lang_menu = pystray.Menu(*lang_items)
        
        # Estado iCUE
        is_icue = self.protocol.is_icue_running()
        icue_status = "iCUE: ON" if is_icue else "iCUE: OFF"
        
        menu = pystray.Menu(
            pystray.MenuItem(self.t("update_now"), self.on_update_click),
            pystray.MenuItem(self.t("interval"), interval_menu),
            pystray.MenuItem(icue_status, None, enabled=False),
            pystray.MenuItem(self.t("language"), lang_menu),
            pystray.MenuItem("---", None, enabled=False),
            pystray.MenuItem(self.t("exit"), self.on_exit_click)
        )
        
        if self.tray_icon:
            self.tray_icon.menu = menu
    
    def on_exit_click(self, icon, item):
        """Manejador para 'Salir'"""
        print("\n👋 Saliendo de la aplicación...")
        self.monitoring = False
        self.protocol.close()
        if self.tray_icon:
            self.tray_icon.stop()
        sys.exit(0)
    
    def _process_battery_result(self, result):
        """Procesa el resultado de la lectura de batería"""
        if 'error' in result:
            print(f"  ❌ Error: {result['error']}")
            if result.get('disconnected'):
                self._update_tray('disconnected', self.t("disconnected"))
            else:
                self._update_tray('error', f"Error: {result['error'][:30]}")
            return
        
        percentage = int(round(result['percentage']))  # Entero
        charging = result['is_charging']
        
        # Actualizar estado
        self.current_level = percentage
        self.current_status = result['charging_text']
        
        # Notificaciones de batería baja (solo si estado es válido y no cargando)
        charging_state = result.get('charging_state', 0)
        if not charging and charging_state in [2]:  # Solo cuando discharging
            self._check_battery_notifications(percentage)
        
        # Determinar icono y texto
        if charging:
            icon_key = 'charging'
            status_text = f"⚡ {percentage}%"
        else:
            rounded_level = (percentage // 10) * 10
            icon_key = max(0, min(100, rounded_level))
            status_text = f"↓ {percentage}%"
        
        # Actualizar icono
        self._update_tray(icon_key, status_text)
        
        # Mostrar en consola
        status_console = f"{status_text} ({self.t('charging') if charging else self.t('discharging')})"
        print(f"  ✅ [{result['timestamp']}] {status_console}")
        if 'raw_data' in result:
            print(f"  📊 Datos: {result['raw_data']}")
    
    def _check_battery_notifications(self, percentage):
        """Envía notificaciones de batería baja/crítica"""
        if percentage <= self.CRITICAL_THRESHOLD and not self.critical_battery_notified:
            self._show_notification("🔴 Batería CRÍTICA", f"¡Solo queda {percentage:.0f}%!", 10)
            self.critical_battery_notified = True
            self.low_battery_notified = True
        elif percentage <= self.LOW_THRESHOLD and not self.low_battery_notified:
            self._show_notification("⚠️ Batería BAJA", f"Nivel: {percentage:.0f}%", 5)
            self.low_battery_notified = True
        elif percentage > self.LOW_THRESHOLD:
            self.low_battery_notified = False
            self.critical_battery_notified = False
    
    def _show_notification(self, title, message, urgency):
        """Muestra notificación del sistema (Windows)"""
        try:
            from win10toast import ToastNotifier
            toaster = ToastNotifier()
            toaster.show_toast(title, message, duration=5, threaded=True)
        except ImportError:
            print(f"  📢 {title}: {message}")
    
    def _update_tray(self, icon_key, tooltip):
        """Actualiza el icono en la bandeja"""
        if self.tray_icon:
            icon = self.icons.get(icon_key, self.icons['error'])
            self.tray_icon.icon = icon
            self.tray_icon.title = tooltip
    
    def monitoring_loop(self):
        """Bucle principal de monitoreo"""
        print(f"  🔄 Iniciando bucle de monitoreo")
        
        while self.monitoring:
            try:
                result = self.protocol.get_battery_info()
                self._process_battery_result(result)
            except Exception as e:
                print(f"  ⚠️ Error en bucle: {e}")
            
            # Esperar intervalo - reiniciar contador cada segundo para detectar cambios
            elapsed = 0
            target = self.update_interval
            while elapsed < target and self.monitoring:
                time.sleep(1)
                elapsed += 1
                # Verificar si el intervalo cambió
                if self.update_interval != target:
                    target = self.update_interval
                    elapsed = 0  # Reiniciar conteo
    
    def start(self, minimized=False):
        """Inicia el monitor"""
        print("🚀 Iniciando monitor HS80 (Versión Final)...")
        print(f"   Idioma: {self.lang}, Intervalo: {self.update_interval}s")
        print("=" * 60)
        
        # Conectar
        if not self.protocol.connect():
            print("⚠️ No se pudo conectar inicialmente")
        
        # Crear menú inicial con marcas de verificación
        interval_items = []
        for sec in self.INTERVAL_OPTIONS:
            label = f"{sec} seg" if sec < 60 else "1 min"
            if sec == self.update_interval:
                label = f"✓ {label}"
            interval_items.append(pystray.MenuItem(label, self._make_interval_handler(sec)))
        interval_menu = pystray.Menu(*interval_items)
        
        # Menú de idioma
        lang_items = [
            pystray.MenuItem("✓ Español" if self.lang == "ES" else "Español", self._make_lang_handler("ES")),
            pystray.MenuItem("✓ English" if self.lang == "EN" else "English", self._make_lang_handler("EN"))
        ]
        lang_menu = pystray.Menu(*lang_items)
        
        # Estado iCUE
        is_icue = self.protocol.is_icue_running()
        icue_status = "iCUE: ON" if is_icue else "iCUE: OFF"
        
        menu = pystray.Menu(
            pystray.MenuItem(self.t("update_now"), self.on_update_click),
            pystray.MenuItem(self.t("interval"), interval_menu),
            pystray.MenuItem(icue_status, None, enabled=False),
            pystray.MenuItem(self.t("language"), lang_menu),
            pystray.MenuItem("---", None, enabled=False),
            pystray.MenuItem(self.t("exit"), self.on_exit_click)
        )
        
        # Icono inicial
        self.tray_icon = pystray.Icon(
            "hs80_battery_monitor",
            icon=self.icons['disconnected'],
            title="HS80 Monitor - Iniciando...",
            menu=menu
        )
        
        # Leer batería una vez inicialmente
        print("\n🔋 Lectura inicial de batería...")
        result = self.protocol.get_battery_info()
        self._process_battery_result(result)
        
        # Iniciar hilo de monitoreo
        self.monitoring = True
        self.update_thread = threading.Thread(target=self.monitoring_loop, daemon=True)
        self.update_thread.start()
        
        print("\n✅ Monitor iniciado correctamente")
        print("   • Icono visible en bandeja del sistema")
        print("   • Click DERECHO para ver el menú")
        print(f"   • Actualización automática cada {self.update_interval} segundos")
        print("=" * 60)
        
        # Ejecutar icono (esto bloquea hasta que se cierra)
        try:
            self.tray_icon.run()
        except Exception as e:
            print(f"\n❌ Error en tray icon: {e}")
            traceback.print_exc()
        finally:
            self.monitoring = False
            self.protocol.close()

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='HS80 Battery Monitor')
    parser.add_argument('--lang', choices=['ES', 'EN'], help='Idioma / Language')
    parser.add_argument('--interval', type=int, help='Intervalo de actualización en segundos')
    parser.add_argument('--minimized', action='store_true', help='Iniciar minimizado')
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print("🎧 HS80 RGB WIRELESS - MONITOR DEFINITIVO")
    print("="*60)
    print("GitHub: https://github.com/CogoJohn/HS80PowerMonitor")
    print("="*60)
    
    try:
        monitor = HS80TrayMonitor()
        
        # Aplicar argumentos si se proporcionan
        if args.lang:
            monitor.lang = args.lang
        if args.interval and args.interval in monitor.INTERVAL_OPTIONS:
            monitor.update_interval = args.interval
        
        monitor.start(minimized=args.minimized)
    except KeyboardInterrupt:
        print("\n👋 Interrumpido por usuario")
    except Exception as e:
        print(f"\n❌ Error fatal: {e}")
        traceback.print_exc()
        input("\nPresiona Enter para salir...")

if __name__ == "__main__":
    main()
    