# Déploiement conteneur : contrôle de vie et limites de sécurité

L’image configure un `HEALTHCHECK` Docker qui fait un GET local sur `/`. Le contrôle confirme seulement que le serveur HTTP répond; il ne vérifie ni les fournisseurs d’IA, ni les clés, quotas, espace disque, persistance, migrations ou capacité à traduire. L’interface HTML peut répondre alors qu’une traduction échouerait. Consultez `docker compose ps` pour l’état Docker.

## Exposition réseau — important

Cette application reste conçue pour un utilisateur de confiance sur une machine privée. À l’état de cette branche, les routes de traduction, paramètres, historique et fichiers ne disposent pas d’une authentification par compte ni d’une isolation multi-utilisateur. Le contrôle d’origine/CORS n’est pas une authentification. Ne publiez pas directement le port HTTP sur Internet ni derrière un proxy public sans mettre en place et auditer une authentification et une autorisation couvrant toutes les routes, une isolation des données et une gestion sûre des secrets. La terminaison TLS seule ne suffit pas.

Compose lie actuellement le port à `127.0.0.1`; conservez cette limite si vous n’avez pas de couche d’accès privée. Une mise en production partagée exige notamment authentification, cloisonnement des sessions et fichiers, stockage durable adapté, limites de téléversement/quotas, gestion des secrets, sauvegardes et tests de sécurité. Ces éléments ne sont pas fournis par le `HEALTHCHECK`.
