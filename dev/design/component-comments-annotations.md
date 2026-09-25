# Stack : versioning, vues partagées, provenance, annotations, commentaires, review

Note du 2026-09-24. Réunit :

- **#915** (open) : ingestion automatisée + versioning Delta des datasets (provenance dans chaque commit Delta, `/deltatables/history/{dc_id}`, `depictio data versions/vacuum`). +16k, 109 fichiers.
- **#919** (open) : historique de versions des dashboards (ledger par famille d'onglets, pins, preview `?version=`, restore non destructif). +5.7k, 38 fichiers. Closes #95.
- **#924** (open) : time travel des données, deux axes (layout x données), picker de version par collection, historique et compare par composant, preview qui épingle les données. +30k, 200 fichiers, porte #915 + #919. Une branche parallèle (`claude/dashboard-versioning-stages-3-5-lk3xh2`, 41 commits) reste à réconcilier.
- **#936** : vue partageable (filtres appliqués).
- **#931** : provenance pipeline (params, filtres pré/pendant pipeline) affichée dans les dashboards.
- **#1106** (Datawrapper) : item 4 **annotation layer** (notes, lignes de référence, plages surlignées), item 16 **commentaires / @mentions**, item 1 **source / notes / "get the data"**, item 12 historique (= #919).
- Les deux notes précédentes : `template_docs_metadata_idea.md` (statut, reviewers dans les métadonnées) et la discussion review/feedback (outreach nf-core, lien feedback, formulaire d'issue).

## L'idée qui relie tout : l'ancre

Tout objet de collaboration (vue partagée, annotation, commentaire, retour de review) pointe vers
**une ancre** qui rend l'état reproductible :

| Partie de l'ancre | Vient de |
|---|---|
| famille de dashboard, onglet, composant (id stable) | ids stables (04599f74f) et #924 (les ids ne sont plus régénérés à l'import) |
| version du dashboard (`version_id`) | #919 |
| versions des données (DC -> commit Delta) | #915 + #924 (pins) |
| état de vue : filtres, sélection, onglet | #936, lien `#filters=` existant |
| sélection en espace données (optionnelle) | outils de sélection existants (box, lasso, range, groupes d'analyse) |

Sans #919/#924, un commentaire ou une annotation pointe vers un état qui n'existe plus au
prochain save ou au prochain ingest. **Le versioning est donc la fondation, pas une feature voisine.**

## Les objets construits sur l'ancre

1. **Vue partagée** (#936) : ancre sans sélection ni texte. Lien ou vue nommée.
2. **Provenance** (#931, #1106 item 1) : panneau par composant, en lecture seule :
   fichier brut + run -> recipe (code, lien GitHub) -> data collection (commit Delta, sa provenance
   #915) -> définition du composant (version #919) -> filtres actifs. Côté pipeline :
   `pipeline_info/params.json` (cf. idée d'introspection des params Nextflow).
3. **Annotation** (le mode Datawrapper-like, étendu au lecteur) : une **sélection nommée et commentée**,
   en espace données, pas en pixels.
   - Géométrie : `x_range` / `y_range` (pic, région sur un area chart), `point_ids` (nuage de points
     sur un scatter, via la colonne de sélection), polygone lasso en coordonnées données, région
     génomique (genome_view, Manhattan).
   - Création depuis les outils de sélection existants : action « Annoter la sélection » dans la barre
     d'actions de sélection. Les groupes d'analyse (lasso -> groupe) sont déjà une sélection nommée :
     l'annotation les généralise (label, note, couleur, visibilité).
   - Rendu : shapes Plotly (`vrect`, `hrect`, surlignage de points) dans figure et advanced_viz.
   - Deux couches à ne pas mélanger :
     - **annotations d'auteur** : font partie du dashboard, donc de ses versions (#919 : `TabSnapshot`
       est `extra="forbid"`, le champ doit y être ajouté explicitement) ;
     - **annotations de lecteur / reviewer** : overlay stocké à part, qui référence un `version_id`,
       n'entre jamais dans les snapshots du dashboard.
   - Données qui changent : une annotation par `point_ids` sur une nouvelle version affiche
     « 12/15 points retrouvés » plutôt que de disparaître ou de mentir.
4. **Commentaires** (#1106 item 16) : fil attaché à une ancre ou à une annotation. Réponses,
   résolu/rouvert, `@mention`, notifications via le websocket existant. Pas d'édition collaborative.
   Clic sur un fil = restaurer l'ancre (vue, sélection, version, données).
5. **Lien de review** : vue figée (version + pins) avec le rôle **commentateur**. Protection :
   `vacuum` ne supprime jamais un commit Delta référencé par une annotation ou un fil ouvert.
6. **Profils de review et destinations** : la review nf-core devient une configuration :
   catégories Wrong / Missing / Moved / Conventions / Hard to read / Go, export d'un fil vers une
   issue ou Discussion GitHub, crédit reviewer (`status`, `reviewers` dans les métadonnées du
   template). Même chose pour les modules du Tools Catalogue (ancre sur le module et sa fixture).

## Stack de PRs proposée

Ordre de merge ; chaque PR est utilisable seule.

| # | PR | Dépend de | Taille | Remarques |
|---|---|---|---|---|
| 0a | Réconcilier #924 v1/v2, rebaser #915 -> #919 -> #924 sur main, les lier en stack | - | M | bloquant ; envisager de découper #924 (200 fichiers) pour la review |
| 0b | Merger #915, #919, #924 | 0a | - | fondation |
| 1 | **ViewState** : modèle (onglet, filtres, sélections, `version_id`, pins) sérialisable en URL et en « vue nommée » ; remplace le `#filters=` ad hoc | 0b | M | ferme #936 |
| 2 | **Provenance** par composant (panneau Source) + bloc source/notes (#1106-1) | 0b | M | ferme #931 (partie affichage), lecture seule |
| 3 | **Annotations** : modèle `Annotation {anchor, geometry, label, note, color, visibility, layer: author/reader, author}`, API CRUD, rendu figure + advanced_viz, « Annoter la sélection », panneau latéral | 1 | L | #1106-4 ; réutilise groupes d'analyse et sélection |
| 4 | **Commentaires** : fils sur ancre ou annotation, résolu, mentions, notifications | 1 (3 optionnel) | L | #1106-16 |
| 5 | **Partage de review** : rôle commentateur, lien figé, rétention des commits Delta référencés | 1, 3, 4 | M | invitation nominative ou login GitHub/ORCID ; pas d'anonyme |
| 6 | **Review profiles + export GitHub + crédit** : catégories nf-core, export fil -> issue, `status`/`reviewers` | 4, note métadonnées templates | M | remplace à terme le lien feedback global par un « Signaler » par composant |

Parallélisable : 2 en parallèle de 1 ; 3 et 4 en parallèle une fois 1 mergée.

## Points d'attention

- **Taille de la fondation** : #924 fait +30k/200 fichiers et embarque #915/#919 ; sa revue est le vrai goulot.
  Les trois PRs datent du 2026-09-14, probablement en conflit avec main aujourd'hui.
- **Re-ingest** : aujourd'hui il accumule (cf. mémoire), les ancres doivent tenir sur les ids stables.
- **Vacuum / rétention** : un pin non protégé casse la restauration ; afficher « données plus disponibles ».
- **Confidentialité** : annotations et commentaires héritent des permissions du projet, jamais d'un lien plus large.
- **Mode public** : lecture seule, pas de commentaires anonymes.
- **Scope** : fils + résolu + mentions ; pas de co-édition temps réel (#1106-18 reste exploratoire).

## Prochaine étape possible

Ouvrir un **[Epic]** qui liste ce stack, relie #915, #919, #924, #936, #931, #1106 (items 1, 4, 16)
et crée les sous-issues 1 à 6 (en anglais).

## Décision du 2026-09-24 : commentaires + annotations d'abord, versioning ensuite

Priorité utilisateur : commentaires et annotations de composants (style Datawrapper) **avant** le lien au versioning.

- V1 indépendante de #915/#919/#924. Ancre = dashboard, onglet, composant (index, stable entre saves ; titre + tag en secours après import), contexte de vue (filtres, sélection).
- Empreintes informatives seulement : hash de config du composant, version Delta courante par DC -> avertissements « composant modifié » / « données modifiées », pas de restauration exacte.
- Champs `version_id` et `pins` réservés, vides en V1, remplis quand le versioning est mergé.
- Toutes les annotations V1 = surcouche partagée hors définition du dashboard ; la couche auteur attend le versioning.
- PRs : (1) modèles + API + permissions + tests ; (2) commentaires dans le viewer ; (3) annotations (« Annoter la sélection », rendu figure/scatter/area puis advanced_viz). Plus tard : pins, rôle commentateur, lien de review, export GitHub.

## Spec V1 retenue (2026-09-24) : commentaires seuls

- **Qui** : éditeurs et owners du projet uniquement (lecture et écriture). Viewers, public, anonymes : rien n'est visible (l'API renvoie 403, l'UI ne montre ni badge ni tiroir).
- **Sur quoi** : un composant, tous types (figures, tables, cartes, advanced_viz), ou l'onglet lui-même.
- **Sélection jointe, optionnelle** : si une sélection est active au moment d'écrire (points, barres, lignes), elle est stockée avec le commentaire (« 42 points sélectionnés ») et réappliquée au clic, avec les filtres actifs. Sans sélection, le commentaire porte sur le composant entier. Réutilise la sélection existante, rien n'est dessiné.
- **Flag « données modifiées »** : empreinte des données (dernier `aggregation_hash` de chaque DC lue par le composant) et de la définition du composant, prises à la création ; comparées à la lecture. Affichage : badge sur le commentaire. Pas de notification, pas de restauration.
- **Fils** : réponses, résolu/rouvert. Pas de mentions ni de notifications en V1.
- **Affichage** : badge compteur dans la barre d'icônes du composant (fils ouverts) + tiroir latéral : fils du composant cliqué, ou tous les fils de l'onglet groupés par composant ; clic sur un fil = défiler jusqu'au composant, le surligner, réappliquer filtres et sélection. Bouton « Nouveau commentaire » dans le tiroir.
- **Hors V1 (vague 2+)** : annotations dessinées (plages, points marqués), commentaires pour viewers ou reviewers externes, mentions et notifications, lien au versioning (pins, restauration exacte), export GitHub.
- **Découpage** : PR A = modèle + API + permissions + flag + suppression en cascade avec le dashboard + backup ; PR B = badge + tiroir dans le viewer.
- **Code** : brouillon de modèles dans le worktree `depictio-worktrees/feat-component-comments` (`depictio/models/models/comments.py`, contient encore les annotations : à retirer pour la V1).

## Ajout à la même PR (2026-09-24) : annotations façon Datawrapper

Référence Datawrapper (onglet Annotate) : range highlights (clic-glisser, derrière les données, couleur/opacité/hachures) et lignes (clic, devant, largeur/style) sur barres, colonnes, lignes, aires, scatter, dot, waterfall ; annotations texte rattachées à une ligne de données, flèche ou cercle vers la donnée, légende numérotée sur mobile ; « highlight labeled symbols ».
Sources : datawrapper.de/academy/range-highlights-and-lines, /academy/customizing-your-scatter-plot-annotate, /blog/annotations-in-bar-charts.

Décisions :
- **Une annotation = un fil de commentaire qui porte une forme** (`annotation: {kind, geometry, label, color, style, published}`), un seul système : même badge, même tiroir, même flag « données modifiées ».
- **4 types, en coordonnées données** : plage x/y (bande derrière les données, label) ; ligne de référence (pointillé devant, label) ; points/barres marqués (cerclés ou contourés, légèrement agrandis ; lignes de table surlignées) ; note fléchée (pastille numérotée + flèche vers un point ou une barre).
- **Signe distinctif** : pastille numérotée ①② dans la couleur de l'annotation, reprise dans le tiroir.
- **Visibilité** : interrupteur « visible par les lecteurs » par annotation. Défaut : interne (éditeurs/owners). Publiée : les viewers voient forme et label, jamais le fil.
- **Création** : mode Annoter dédié (icône dans la barre d'actions du composant) : glisser = plage, clic = ligne ou note, lasso/box = points, sans filtrer le reste du dashboard ; popover label, couleur, commentaire optionnel.
- **Couverture V1** : figures Plotly et advanced_viz Plotly (histogramme, barres, aires, lignes, scatter, Manhattan, volcano, UMAP) + surlignage de lignes dans les tables. genome_view (GenomeSpy) et cartes : vague suivante.
- Rendu côté client (shapes/annotations Plotly ajoutées au rendu), pas de recalcul serveur.

## Compatibilité agents IA : à prévoir dès la V1 (2026-09-24)

Seulement des champs et des règles d'API ; MCP, jetons à portée limitée et runner d'agents viendront plus tard, sans migration.

- **Auteur typé** : `author: {kind: "human" | "agent", user_id, agent: {name, model, run_id, on_behalf_of}}`. Un agent agit toujours pour le compte d'un utilisateur. UI : pastille « Agent » + nom de la personne qui l'a lancé.
- **Statut `proposed`** : fils et annotations créés par un agent naissent proposés ; un humain les accepte (deviennent normaux) ou les rejette. Une annotation d'agent ne peut pas être publiée aux lecteurs sans validation humaine.
- **Preuve structurée optionnelle** : `evidence: [{claim, query, values, view_state}]` à côté du texte libre, pour vérifier en un clic (vue restaurée) et relire par un autre agent.
- **Idempotence** : `dedupe_key` (hash ancre + affirmation) + `run_id` ; relancer un agent met à jour ses propositions au lieu de dupliquer ; plafond par run.
- **Retour humain conservé** : accepté / rejeté / modifié + motif optionnel (futur jeu d'évaluation).
- **Schémas propres dans l'OpenAPI** (modèles Pydantic stricts, géométrie en coordonnées données).
- Règle à garder en tête : le texte des commentaires est une donnée, jamais une instruction pour un agent (injection de prompt).

## Intégration avec les templates nf-core lot 2 (2026-09-25)

Branche `integ/lot2-comments` : #1109 mergée dans `feat/nfcore-templates-lot2` (#1102). La structure de lot 2 est gardée, les annotations y sont rebranchées.

- **Renderers devenus des wrappers** : MA et QQ ouvrent `VolcanoRenderer` sur leur vue, enrichment ouvre `DotPlotRenderer` (vue `enrichment`), ROC ouvre `PrBenchmarkRenderer` (vue `roc`). La couche d'annotation vit dans le renderer qui dessine la figure ; `supportsAdvancedVizAnnotation` couvre `volcano`, `dot_plot` et `pr_benchmark`.
- **Annotation par vue** : quand une tuile propose plusieurs vues aux axes différents (volcano / MA / QQ, marker / enrichment, PR / ROC), `variant` vaut la vue active. Une marque posée sur une vue n'apparaît pas sur les autres. Les annotations sans `variant` (créées avant) restent visibles sur toutes les vues.
- **Identifiant de point par vue** : QQ garde l'id de feature en slot 0 ; volcano et MA gardent le label (`label_col` sinon `feature_id_col`) ; enrichment garde le terme en slot 3.
- **Sélection croisée** : les handlers de lot 2 protégés par `useGestureGuardedSelection` passent par `annotations.plotProps({...})` (scatter_xy, profile, manhattan). En mode Annoter la couche les débranche, donc un tracé d'annotation ne vide ni ne pose de sélection.
- **Barre d'actions** : le bouton « Clear selection (N) » de lot 2 remplace l'ancien reset actif ; les états persistants commentaires et annoter de #1109 s'y ajoutent.
- **Tables** : la colonne épinglée des badges d'annotation (48 px) est exclue de l'auto-fit des colonnes de lot 2 (`suppressAutoSize`, `suppressSizeToFit`).
- **coverage_track** : le hook est appelé avant le retour anticipé de la vue Locus (ordre des hooks stable) et désactivé dans cette vue, dessinée par GenomeSpy.
- **Lollipop** : annotations actives seulement quand un seul gène est affiché (règle de #1109 conservée).
