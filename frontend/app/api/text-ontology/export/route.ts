// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// Render an ontology as Mermaid, RDF/OWL (Turtle), Neo4j Cypher or an
// interactive HTML graph. Pure computation on the request body.
export const POST = withPermission({ catalog: ['read'] })((req) => proxyToBackend(req));
