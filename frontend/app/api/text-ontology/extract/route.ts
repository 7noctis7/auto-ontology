// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// Extract an ontology (classes, triplets, attributes) from free text. It reads
// the glossary when asked to reuse it and writes nothing, so catalog:read is
// enough, the same tier that may list the Terms.
export const POST = withPermission({ catalog: ['read'] })((req) => proxyToBackend(req));
