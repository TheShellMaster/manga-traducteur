# 📱 Intégration Android — Cycle de Vie & Barre des Tâches Mobiles

Ce document détaille l'intégration du cycle de vie du serveur local de **Manga Translator Studio** dans le système d'exploitation Android (Barre des tâches récentes & Barre de notifications).

---

## 1. Barre des Tâches Mobiles (Écran des Applications Récentes / Multitâche)

Sur Android, la « barre des tâches » correspond à l'**Écran des applications actives récentes** (Recent Apps Overview / Multitasking), accessible en glissant du bas de l'écran ou en appuyant sur le bouton carré.

### Comportement Attendu :
Quand l'utilisateur glisse (swipe) la carte de Manga Translator Studio hors de la liste des applications actives pour la fermer, **le serveur local FastAPI/Uvicorn doit s'éteindre immédiatement** pour ne pas vider la batterie du téléphone ni monopoliser le port 8000.

### Implémentation du Cycle de Vie Android :
Dans le Service Android d'arrière-plan (`MangaServerService.kt`), intercepter l'événement `onTaskRemoved` :

```kotlin
class MangaServerService : Service() {

    override fun onTaskRemoved(rootIntent: Intent?) {
        super.onTaskRemoved(rootIntent)
        Log.d("MangaTranslator", "Application fermée depuis la barre des tâches récentes -> Arrêt du serveur.")

        // 1. Envoi de la requête d'extinction propre
        CoroutineScope(Dispatchers.IO).launch {
            try {
                val url = URL("http://127.0.0.1:8000/api/system/shutdown")
                val conn = url.openConnection() as HttpURLConnection
                conn.requestMethod = "POST"
                conn.connectTimeout = 1500
                conn.responseCode
            } catch (e: Exception) {
                // Serveur déjà arrêté
            }
        }

        // 2. Destruction du processus local
        stopSelf()
    }

    override fun onDestroy() {
        super.onDestroy()
        // Tue le sous-processus Python / Chaquopy si encore actif
        android.os.Process.killProcess(android.os.Process.myPid())
    }
}
```

---

## 2. Notification Permanente avec Bouton « Arrêter » (Barre d'État Android)

Sur Android 8+, tout serveur local persistant doit s'exécuter comme un **Foreground Service**. Il affiche une notification active dans la barre de notifications supérieure avec un bouton d'action directe :

```kotlin
val stopIntent = Intent(this, StopServerReceiver::class.java)
val stopPendingIntent = PendingIntent.getBroadcast(
    this, 0, stopIntent, PendingIntent.FLAG_IMMUTABLE
)

val notification = NotificationCompat.Builder(this, CHANNEL_ID)
    .setContentTitle("Manga Translator Studio")
    .setContentText("Serveur local actif sur http://127.0.0.1:8000")
    .setSmallIcon(R.drawable.ic_manga_tray)
    .setOngoing(true)
    .addAction(R.drawable.ic_stop, "🛑 Arrêter le Serveur", stopPendingIntent)
    .build()

startForeground(NOTIFICATION_ID, notification)
```

Dès que l'utilisateur clique sur **« 🛑 Arrêter le Serveur »** dans sa barre de notifications ou ferme l'application depuis la barre des tâches récentes, le serveur local s'arrête sans laisser de processus fantôme.
