/* Developer integration entry point. Loaded after core.js and before boot.js.
 *
 * Attach the existing application's consultation client here:
 *   window.PAI.submitConsult = function (payload) { return aPromise; };
 *
 * payload:
 *   packageId, use, contactMethod ('phone' | 'email'), contact,
 *   name, company, request, contactRequested (boolean)
 *
 * Resolve with the actual server outcome:
 *   { status: 'accepted', requestId: 'server-issued-id' }
 *   { status: 'pending' }
 *   { status: 'failed' }
 *
 * Only 'accepted' shows a completed receipt. A rejection or unknown response
 * shows unconfirmed receipt. No adapter means no request and an inline error.
 * contactRequested is a contact request, not privacy-policy consent. Connect
 * the operating service's approved privacy notice and consent requirements.
 * Never place secrets or service credentials in this browser file.
 * This delivery deliberately leaves the adapter undefined.
 */

/* PC finder adapter — separate from human consultation above.
 * Attach PAI.sendPCMessage(payload) to the existing verified AI client.
 * payload: { text, history:[{role,text}], selectedProductId, source,
 *            conditions:{purpose,budget,environment} }
 * Resolve: { reply: string, products?: Array<string|{id:string}>,
 *            conditions?: {purpose?,budget?,environment?} }
 * This is a UI contract, NOT the deployed /api/talk/parse contract.
 * Map product ids to the real sales catalog and translate session/display_context
 * in the adapter. Return only verified catalog ids from PAI.data.products.
 * Do not turn a quote save into permission to contact the customer.
 * See ../../../PC-FINDER-INTEGRATION.md in the delivery folder.
 * An absent adapter sends no request, preserves the draft, and shows an error.
 */
