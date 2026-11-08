"use strict";
// Runs a proxy auto-config file the way a browser does.
//
// Reads {pac, hosts} as JSON on stdin and prints, as JSON, what
// FindProxyForURL returns for https://<host>/ with each host. The standard
// PAC functions are defined as Firefox defines them. Every function that
// looks a name up throws, so a file that would look one up fails the run.

const fs = require("fs");
const vm = require("vm");

const input = JSON.parse(fs.readFileSync(0, "utf8"));

function lookup(name) {
  return function () {
    throw new Error(`the file called ${name}, which looks a name up`);
  };
}

const sandbox = {
  isPlainHostName(host) {
    return host.search("(\\.)|:") == -1;
  },
  dnsDomainIs(host, domain) {
    return host.length >= domain.length && host.substring(host.length - domain.length) == domain;
  },
  localHostOrDomainIs(host, hostdom) {
    return host == hostdom || hostdom.lastIndexOf(host + ".", 0) == 0;
  },
  shExpMatch(url, pattern) {
    pattern = pattern.replace(/\./g, "\\.").replace(/\*/g, ".*").replace(/\?/g, ".");
    return new RegExp("^" + pattern + "$").test(url);
  },
  isResolvable: lookup("isResolvable"),
  isInNet: lookup("isInNet"),
  isInNetEx: lookup("isInNetEx"),
  dnsResolve: lookup("dnsResolve"),
  dnsResolveEx: lookup("dnsResolveEx"),
  myIpAddress: lookup("myIpAddress"),
  myIpAddressEx: lookup("myIpAddressEx"),
};
vm.createContext(sandbox);
vm.runInContext(input.pac, sandbox, { filename: "proxy.pac" });

const results = {};
for (const host of input.hosts) {
  const url = (input.scheme || "https") + "://" + (host.indexOf(":") >= 0 && host[0] != "[" ? "[" + host + "]" : host) + "/";
  results[host] = sandbox.FindProxyForURL(url, host);
}
process.stdout.write(JSON.stringify(results));
