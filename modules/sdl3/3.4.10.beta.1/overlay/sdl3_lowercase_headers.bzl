def _lowercase_headers_impl(ctx):
    outputs = []
    for src in ctx.files.srcs:
        out = ctx.actions.declare_file(ctx.attr.out_dir + "/" + src.basename.lower())
        ctx.actions.symlink(output = out, target_file = src)
        outputs.append(out)
    return DefaultInfo(files = depset(outputs))

lowercase_headers = rule(
    implementation = _lowercase_headers_impl,
    attrs = {
        "out_dir": attr.string(mandatory = True),
        "srcs": attr.label_list(allow_files = True, mandatory = True),
    },
)
