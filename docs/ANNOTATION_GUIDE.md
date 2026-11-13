# Annotation guide

## Label fields

Each patch has one primary broad category: `barchan_crescent_dune`, `linear_dune`, `other_dune`, `rocky_ridge_layered`, `other_non_dune`, or `unknown`. Keep morphology separate from geological origin and process interpretation.

Record label confidence as `verified`, `tentative`, or `unknown`, plus annotator ID, review date, evidence URL/product, and a short rationale. The retrieval model must not provide the evidence used to assign its own evaluation labels.

## Recognition cues

- **Barchan/crescent dunes:** isolated crescentic sand bodies with a discernible slip face and horns; record whether wind direction is inferred or independently known.
- **Linear dunes:** elongated, broadly parallel ridges with persistent axial trends; distinguish from bedrock lineations and yardangs.
- **Other dunes:** aeolian bedforms that can be identified as dunes but do not fit the first two classes; retain a subtype note where supportable.
- **Rocky ridges/layered terrain:** exposed bedrock ridges, strata, or repeated layers; do not infer lithology from grayscale texture alone.
- **Other non-dune terrain:** confidently non-dune surfaces; state the observed form if known.
- **Unknown:** occlusion, resolution, illumination, mixed landforms, or source context prevents a defensible decision.

## Review procedure

Annotators inspect source context and patch preview, coordinates, scale, acquisition metadata, and provider record. They first assign the visible morphology without seeing model rankings. Geological process and cross-planetary relevance are separate later judgements. Evaluation relevance judgements must cite their supporting evidence and may be `relevant`, `not_relevant`, `uncertain`, or `not_reviewed` at both category and morphology levels.

No annotations have yet been independently reviewed. Until that work is performed, all model quality metrics and analogue claims are unavailable.
