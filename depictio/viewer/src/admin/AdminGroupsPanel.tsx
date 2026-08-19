import React from 'react';

import GroupsWorkspace from '../groups/GroupsWorkspace';

/** Sysadmin surface for user groups: every group in the deployment, with
 *  create/rename/delete, membership and P.I. designation. The same
 *  master-detail workspace backs `/groups`, where it is scoped to the
 *  caller's own groups. */
const AdminGroupsPanel: React.FC = () => <GroupsWorkspace scope="admin" />;

export default AdminGroupsPanel;
