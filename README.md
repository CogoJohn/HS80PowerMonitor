# 🎧 HS80 Battery Monitor

Monitor de batería para auriculares Corsair HS80 RGB Wireless en Windows.

[![Windows](https://img.shields.io/badge/Windows-10%2F11-blue)](https://github.com/CogoJohn/HS80PowerMonitor)
[![Python](https://img.shields.io/badge/Python-3.8%2B-green)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

## 📱 Capturas de pantalla

```
🔋 85%          - Batería normal (verde)
⚡ 100%         - Cargando (azul)
🔴 15%          - Batería baja (rojo)
```

## ⭐ Características

- 📊 **Monitoreo en tiempo real** del nivel de batería
- 🔔 **Notificaciones** de batería baja (≤20%) y crítica (≤10%)
- 🔄 **Intervalo configurable** (3, 5, 10, 15, 30 o 60 segundos)
- 🌐 **Multidioma** (Español / Inglés)
- 📥 **Inicio automático** con Windows (opcional)
- 🎨 **Icono en bandeja del sistema** con indicador visual
- ⚡ **Compatible con iCUE** (detección automática)
## 📦 Descarga

Ve a [Releases](https://github.com/CogoJohn/HS80PowerMonitor/releases) para descargar la última versión.

## 💻 Instalación

### Instalador (Recomendado)

1. Descarga `HS80Monitor-Setup.exe`
2. Ejecuta el instalador
3. Selecciona tu idioma preferido
4. Configura el intervalo de actualización
5. ¡Listo!

### Portable

1. Descarga `hs80_monitor.exe`
2. Ejecuta directamente

## 🔧 Uso

1. **Icono en bandeja**: Muestra el porcentaje de batería
2. **Click derecho**: Menú contextual
   - Actualizar ahora
   - Cambiar intervalo
   - Cambiar idioma
   - Salir
3. **Notificaciones**: Se muestran cuando la batería baja del 20%

## ⌨️ Desarrollo

### Requisitos

- Python 3.8+
- Windows 10/11

### Dependencias

```bash
pip install hidapi pystray Pillow psutil win10toast
```

### Compilar

```bash
# Compilar aplicación
pyinstaller --onefile --noconsole hs80_monitor.py

# Compilar instalador
pyinstaller --onefile --noconsole --add-data "hs80_monitor.exe;." install.py
```

## 🔌 Compatibilidad

| Dispositivo | Vendor ID | Product ID |
|-------------|-----------|------------|
| Corsair HS80 RGB Wireless | 0x1b1c | 0x0a6b |

## ❓ Solución de Problemas

### "No se encontró el dispositivo"
- Verifica que el receptor USB esté conectado
- Prueba con otro puerto USB
- Ejecuta como administrador

### "Error de acceso al dispositivo"
- Cierra iCUE si está abierto
- Otros programas pueden estar usando el dispositivo HID

### Notificaciones no aparecen
- Verifica que las notificaciones estén habilitadas en Windows

## 📝 Configuración

El archivo `preferences.ini` contiene la configuración:

```ini
language=ES
update_interval=30
auto_start=0
```

## 📄 Licencia

MIT License - ver [LICENSE](LICENSE) para detalles.

---

Hecho con ❤️ para la comunidad de Corsair

🔗 GitHub: https://github.com/CogoJohn/HS80PowerMonitor
